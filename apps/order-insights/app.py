from __future__ import annotations

import argparse
import csv
import io
import json
import math
import mimetypes
import sqlite3
import threading
import webbrowser
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATA = ROOT / "data"
DB_PATH = DATA / "wearable_growth.sqlite3"
DEMO_CSV = DATA / "demo_orders.csv"
VALID_STATUSES = {"paid", "completed", "refunded"}
CSV_FIELDS = ["order_no", "customer_id", "order_date", "product_sku", "product_name", "category", "quantity", "amount", "channel", "country", "status"]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def connect_db() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=8)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 8000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def clean_text(value: object, limit: int) -> str:
    return str(value or "").strip()[:limit]


def normalize_order(row: dict) -> dict:
    normalized = {field: clean_text(row.get(field), 120) for field in CSV_FIELDS}
    for field in ("order_no", "customer_id", "order_date", "product_sku", "product_name", "category", "channel", "country", "status"):
        if not normalized[field]:
            raise ValueError("缺少必填字段 " + field)
    try:
        date.fromisoformat(normalized["order_date"])
    except ValueError as exc:
        raise ValueError("order_date 必须使用 YYYY-MM-DD 格式") from exc
    try:
        quantity = int(row.get("quantity", 0))
        amount = round(float(row.get("amount", 0)), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError("quantity 或 amount 不是有效数字") from exc
    if quantity < 1 or not math.isfinite(amount) or amount < 0:
        raise ValueError("quantity 必须大于 0，amount 不能小于 0")
    normalized["quantity"] = quantity
    normalized["amount"] = amount
    normalized["status"] = normalized["status"].lower()
    if normalized["status"] not in VALID_STATUSES:
        raise ValueError("status 仅支持 paid、completed、refunded")
    return normalized


def insert_orders(conn: sqlite3.Connection, orders: list) -> tuple:
    stamp = now_iso()
    inserted = 0
    skipped = 0
    for order in orders:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO orders
               (order_no,customer_id,order_date,product_sku,product_name,category,quantity,amount,channel,country,status,created_at)
               VALUES(:order_no,:customer_id,:order_date,:product_sku,:product_name,:category,:quantity,:amount,:channel,:country,:status,:created_at)""",
            {**order, "created_at": stamp},
        )
        if cursor.rowcount:
            inserted += 1
        else:
            skipped += 1
    return inserted, skipped


def initialize_db() -> None:
    with connect_db() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_no TEXT NOT NULL UNIQUE,
                customer_id TEXT NOT NULL,
                order_date TEXT NOT NULL,
                product_sku TEXT NOT NULL,
                product_name TEXT NOT NULL,
                category TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                amount REAL NOT NULL CHECK(amount >= 0),
                channel TEXT NOT NULL,
                country TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('paid','completed','refunded')),
                created_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS followups (
                customer_id TEXT PRIMARY KEY,
                status TEXT NOT NULL CHECK(status IN ('pending','contacted')),
                note TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )"""
        )
        count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        if count == 0 and DEMO_CSV.exists():
            with DEMO_CSV.open("r", encoding="utf-8-sig", newline="") as source:
                rows = csv.DictReader(source)
                valid = [normalize_order(row) for row in rows]
            insert_orders(conn, valid)


def segment_customer(customer: dict) -> dict:
    last_category = customer["last_category"]
    days_since = customer["days_since_last"]
    cycle_days = 35 if last_category == "配件" else 75
    due = days_since >= cycle_days
    high_value = customer["spend"] >= 1500 or customer["orders"] >= 3
    repeat = customer["orders"] >= 2
    score = min(45, int(days_since / cycle_days * 45))
    score += 20 if repeat else 0
    score += 15 if customer["spend"] >= 1000 else 0
    score += 15 if due else 0
    score = min(score, 100)

    if due:
        segment = "待跟进"
    elif high_value:
        segment = "高价值"
    elif repeat:
        segment = "复购客户"
    else:
        segment = "新客"

    next_products = {
        "智能手表": "替换表带或磁吸充电线",
        "运动手环": "运动表带或备用充电线",
        "智能戒指": "同系列配件或运动手环",
        "运动耳机": "替换耳帽或运动手环",
        "配件": "同系列智能穿戴设备",
    }
    suggestion = next_products.get(last_category, "搭配同系列穿戴配件")
    if due:
        action = "发送使用回访与复购提醒，推荐：" + suggestion
    elif high_value:
        action = "邀请体验新品或会员权益，推荐：" + suggestion
    elif repeat:
        action = "按已购品类做关联搭配，推荐：" + suggestion
    else:
        action = "发送首次使用指南，7 天后回访；可推荐：" + suggestion

    reasons = ["距最近订单 {} 天".format(days_since), "累计 {} 单 / ¥{:,.0f}".format(customer["orders"], customer["spend"])]
    if due:
        reasons.append("达到该品类 {} 天建议回访周期".format(cycle_days))
    elif repeat:
        reasons.append("已有复购记录，可做关联推荐")
    else:
        reasons.append("首购客户，先做使用激活")
    return {
        **customer,
        "segment": segment,
        "cycle_days": cycle_days,
        "due": due,
        "high_value": high_value,
        "repeat": repeat,
        "score": score,
        "suggestion": suggestion,
        "next_action": action,
        "reason": "；".join(reasons),
    }


def build_customers(conn: sqlite3.Connection) -> list:
    orders = conn.execute(
        "SELECT * FROM orders WHERE status IN ('paid','completed') ORDER BY order_date DESC, id DESC"
    ).fetchall()
    followups = {row["customer_id"]: dict(row) for row in conn.execute("SELECT * FROM followups")}
    grouped = {}
    for row in orders:
        order = dict(row)
        grouped.setdefault(order["customer_id"], []).append(order)
    today = date.today()
    customers = []
    for customer_id, rows in grouped.items():
        latest = rows[0]
        last_date = date.fromisoformat(latest["order_date"])
        days_since = max(0, (today - last_date).days)
        spend = sum(row["amount"] for row in rows)
        active_90 = [row for row in rows if (today - date.fromisoformat(row["order_date"])).days <= 90]
        customer = {
            "customer_id": customer_id,
            "orders": len(rows),
            "spend": round(spend, 2),
            "last_order_date": latest["order_date"],
            "last_product": latest["product_name"],
            "last_category": latest["category"],
            "last_channel": latest["channel"],
            "country": latest["country"],
            "days_since_last": days_since,
            "orders_90d": len(active_90),
            "followup_status": followups.get(customer_id, {}).get("status", "pending"),
            "followup_note": followups.get(customer_id, {}).get("note", ""),
        }
        customers.append(segment_customer(customer))
    customers.sort(key=lambda c: (c["followup_status"] == "contacted", -c["score"], -c["spend"]))
    return customers


def get_overview(conn: sqlite3.Connection) -> dict:
    paid = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(amount),0) AS amount FROM orders WHERE status IN ('paid','completed')").fetchone()
    totals = conn.execute(
        """SELECT COUNT(*) AS customer_count, SUM(CASE WHEN orders > 1 THEN 1 ELSE 0 END) AS repeat_count
           FROM (SELECT customer_id, COUNT(*) AS orders FROM orders WHERE status IN ('paid','completed') GROUP BY customer_id)"""
    ).fetchone()
    customers = build_customers(conn)
    active_due = sum(1 for c in customers if c["due"] and c["followup_status"] != "contacted")
    count = totals["customer_count"] or 0
    repeat_count = totals["repeat_count"] or 0
    today = date.today()
    months = []
    year, month = today.year, today.month
    for offset in range(5, -1, -1):
        y, m = year, month - offset
        while m <= 0:
            y -= 1
            m += 12
        months.append("{:04d}-{:02d}".format(y, m))
    trend = []
    for label in months:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount),0) AS revenue FROM orders WHERE status IN ('paid','completed') AND substr(order_date,1,7)=?",
            (label,),
        ).fetchone()
        trend.append({"month": label[5:], "revenue": round(row["revenue"], 2)})
    channel_rows = conn.execute(
        "SELECT channel, COUNT(*) AS n FROM orders WHERE status IN ('paid','completed') GROUP BY channel ORDER BY n DESC"
    ).fetchall()
    return {
        "orders": paid["n"],
        "revenue": round(paid["amount"], 2),
        "customers": count,
        "repeat_rate": round((repeat_count / count * 100) if count else 0, 1),
        "repeat_customers": repeat_count,
        "due_followups": active_due,
        "trend": trend,
        "channels": [dict(row) for row in channel_rows],
        "data_note": "初始订单为虚构演示数据；导入真实数据前请确认已获客户授权。",
    }


def safe_csv_value(value: object) -> object:
    text = "" if value is None else str(value)
    if text[:1] in {"=", "+", "-", "@", "\t", "\r"}:
        return "'" + text
    return value


class Handler(BaseHTTPRequestHandler):
    server_version = "WearableGrowth/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print("[{}] {}".format(self.log_date_time_string(), fmt % args))

    def send_json(self, data: object, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_body(self, maximum: int) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("请求长度无效") from exc
        if length < 1 or length > maximum:
            raise ValueError("请求内容为空或超过大小限制")
        return self.rfile.read(length)

    def read_json(self) -> dict:
        try:
            return json.loads(self.read_body(32_000).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("请提交有效的 UTF-8 JSON") from exc

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            with connect_db() as conn:
                self.send_json({"ok": True, "storage": "sqlite", "orders": conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]})
            return
        if parsed.path == "/api/overview":
            with connect_db() as conn:
                self.send_json(get_overview(conn))
            return
        if parsed.path == "/api/customers":
            params = parse_qs(parsed.query)
            q = params.get("q", [""])[0].strip().lower()[:100]
            segment = params.get("segment", [""])[0]
            followup = params.get("followup", [""])[0]
            with connect_db() as conn:
                customers = build_customers(conn)
            if q:
                customers = [c for c in customers if q in (c["customer_id"] + " " + c["last_product"] + " " + c["country"] + " " + c["last_channel"]).lower()]
            if segment:
                customers = [c for c in customers if c["segment"] == segment]
            if followup in {"pending", "contacted"}:
                customers = [c for c in customers if c["followup_status"] == followup]
            self.send_json({"customers": customers, "count": len(customers)})
            return
        if parsed.path == "/api/export.csv":
            with connect_db() as conn:
                customers = build_customers(conn)
            output = io.StringIO(newline="")
            fields = ["customer_id", "segment", "orders", "spend", "last_order_date", "days_since_last", "score", "next_action", "reason", "followup_status"]
            writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows({field: safe_csv_value(customer.get(field)) for field in fields} for customer in customers)
            body = ("\ufeff" + output.getvalue()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename=customer_followups.csv")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/import":
            self.import_csv()
            return
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ["api", "followups"] and parts[3] == "status":
            customer_id = unquote(parts[2])[:120]
            try:
                payload = self.read_json()
                if not isinstance(payload, dict):
                    raise ValueError("请求内容必须是 JSON 对象")
                status = clean_text(payload.get("status"), 20)
                note = clean_text(payload.get("note"), 300)
                if status not in {"pending", "contacted"}:
                    raise ValueError("状态只能是 pending 或 contacted")
                with connect_db() as conn:
                    exists = conn.execute("SELECT 1 FROM orders WHERE customer_id=? LIMIT 1", (customer_id,)).fetchone()
                    if not exists:
                        self.send_json({"error": "没有找到该客户"}, 404)
                        return
                    conn.execute(
                        """INSERT INTO followups(customer_id,status,note,updated_at) VALUES(?,?,?,?)
                           ON CONFLICT(customer_id) DO UPDATE SET status=excluded.status,note=excluded.note,updated_at=excluded.updated_at""",
                        (customer_id, status, note, now_iso()),
                    )
                self.send_json({"customer_id": customer_id, "status": status})
            except ValueError as exc:
                self.send_json({"error": str(exc)}, 400)
            return
        self.send_json({"error": "接口不存在"}, 404)

    def import_csv(self) -> None:
        try:
            raw = self.read_body(4_000_000)
            text = raw.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            missing = set(CSV_FIELDS) - set(reader.fieldnames or [])
            if missing:
                self.send_json({"error": "CSV 缺少列：" + ", ".join(sorted(missing))}, 400)
                return
            valid, errors = [], []
            for row_number, row in enumerate(reader, start=2):
                try:
                    valid.append(normalize_order(row))
                except ValueError as exc:
                    errors.append({"row": row_number, "error": str(exc)})
            with connect_db() as conn:
                inserted, skipped = insert_orders(conn, valid)
            self.send_json({"inserted": inserted, "skipped_duplicates": skipped, "rejected": len(errors), "errors": errors[:8]})
        except (ValueError, UnicodeDecodeError, csv.Error) as exc:
            self.send_json({"error": str(exc)}, 400)

    def serve_static(self, requested: str) -> None:
        if requested == "/sample_orders.csv":
            content = DEMO_CSV.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename=sample_orders.csv")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        relative = "index.html" if requested in ("", "/") else requested.lstrip("/")
        candidate = (STATIC / relative).resolve()
        if not candidate.is_relative_to(STATIC.resolve()) or not candidate.is_file():
            self.send_json({"error": "页面不存在"}, 404)
            return
        content = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    parser = argparse.ArgumentParser(description="穿戴电商订单洞察台")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址；容器部署时用 0.0.0.0")
    parser.add_argument("--port", type=int, default=8781)
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()
    initialize_db()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = "http://{}:{}/".format(args.host, args.port)
    print("订单洞察台已启动：" + url)
    print("数据存储：" + str(DB_PATH))
    if args.open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("正在停止服务…")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
