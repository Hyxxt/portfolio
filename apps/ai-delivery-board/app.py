from __future__ import annotations

import argparse
import json
import mimetypes
import sqlite3
import threading
import webbrowser
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATA = ROOT / "data"
DB_PATH = DATA / "delivery_board.sqlite3"
STATUSES = {"todo", "doing", "done"}
PRIORITIES = {"low", "medium", "high"}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def connect_db() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=8)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 8000")
    return conn


def initialize_db() -> None:
    with connect_db() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 100),
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL CHECK(status IN ('todo','doing','done')),
                priority TEXT NOT NULL CHECK(priority IN ('low','medium','high')),
                due_date TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        if count == 0:
            stamp = now_iso()
            demo = [
                ("拆解需求与验收标准", "明确任务卡片字段、三种状态、筛选条件和验收方式。", "done", "high", ""),
                ("搭建 SQLite 数据模型与任务 API", "完成任务创建、查询、编辑、状态变更和删除接口。", "done", "high", ""),
                ("实现响应式看板和任务卡片", "桌面端三列看板，窄屏可滚动浏览；支持拖放调整状态。", "doing", "high", ""),
                ("补充搜索、优先级筛选与统计", "按关键词和优先级缩小任务范围，顶部统计跟随数据变化。", "doing", "medium", ""),
                ("整理交付说明与人工验收清单", "说明启动方式、API、数据位置和当前实现边界。", "todo", "low", ""),
            ]
            conn.executemany(
                """INSERT INTO tasks(title,description,status,priority,due_date,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?)""",
                [(*item, stamp, stamp) for item in demo],
            )


def serialize(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def validate_payload(payload: object, partial: bool = False) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("请求内容必须是 JSON 对象。")
    allowed = {"title", "description", "status", "priority", "due_date"}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError("包含不支持的字段。")
    result = {}
    if not partial or "title" in payload:
        title = str(payload.get("title", "")).strip()
        if not title:
            raise ValueError("任务标题不能为空。")
        if len(title) > 100:
            raise ValueError("任务标题最多 100 个字符。")
        result["title"] = title
    if not partial or "description" in payload:
        description = str(payload.get("description", "")).strip()
        if len(description) > 1000:
            raise ValueError("任务说明最多 1000 个字符。")
        result["description"] = description
    if not partial or "status" in payload:
        status = str(payload.get("status", "todo"))
        if status not in STATUSES:
            raise ValueError("状态必须是待开始、进行中或已完成。")
        result["status"] = status
    if not partial or "priority" in payload:
        priority = str(payload.get("priority", "medium"))
        if priority not in PRIORITIES:
            raise ValueError("优先级必须是低、中或高。")
        result["priority"] = priority
    if not partial or "due_date" in payload:
        due_date = str(payload.get("due_date", "")).strip()
        if due_date:
            try:
                date.fromisoformat(due_date)
            except ValueError as exc:
                raise ValueError("截止日期格式无效。") from exc
        result["due_date"] = due_date
    if partial and not result:
        raise ValueError("没有可更新的字段。")
    return result


def task_counts(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT status, COUNT(*) AS n FROM tasks GROUP BY status").fetchall()
    counts = {"todo": 0, "doing": 0, "done": 0}
    for row in rows:
        counts[row["status"]] = row["n"]
    return {"total": sum(counts.values()), **counts}


class Handler(BaseHTTPRequestHandler):
    server_version = "DeliveryBoard/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_json(self, data: object, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("请求长度无效。") from exc
        if length < 1 or length > 64_000:
            raise ValueError("请求内容为空或超出 64 KB 限制。")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("请提交有效的 UTF-8 JSON。") from exc

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            with connect_db() as conn:
                self.send_json({"ok": True, "storage": "sqlite", "stats": task_counts(conn)})
            return
        if parsed.path == "/api/tasks":
            params = parse_qs(parsed.query)
            query = params.get("q", [""])[0].strip()[:100]
            priority = params.get("priority", [""])[0]
            status = params.get("status", [""])[0]
            clauses, values = [], []
            if query:
                clauses.append("(title LIKE ? OR description LIKE ?)")
                values.extend([f"%{query}%", f"%{query}%"])
            if priority in PRIORITIES:
                clauses.append("priority = ?")
                values.append(priority)
            if status in STATUSES:
                clauses.append("status = ?")
                values.append(status)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            with connect_db() as conn:
                rows = conn.execute(
                    "SELECT * FROM tasks" + where + " ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, updated_at DESC, id DESC",
                    values,
                ).fetchall()
                self.send_json({"tasks": [serialize(row) for row in rows], "stats": task_counts(conn)})
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/tasks":
            self.send_json({"error": "接口不存在。"}, 404)
            return
        try:
            data = validate_payload(self.read_json())
            stamp = now_iso()
            with connect_db() as conn:
                cursor = conn.execute(
                    """INSERT INTO tasks(title,description,status,priority,due_date,created_at,updated_at)
                       VALUES(:title,:description,:status,:priority,:due_date,:created_at,:updated_at)""",
                    {**data, "created_at": stamp, "updated_at": stamp},
                )
                row = conn.execute("SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone()
            self.send_json({"task": serialize(row)}, 201)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, 400)

    def do_PATCH(self) -> None:
        path = urlparse(self.path).path
        parts = path.strip("/").split("/")
        if len(parts) != 3 or parts[:2] != ["api", "tasks"] or not parts[2].isdigit():
            self.send_json({"error": "接口不存在。"}, 404)
            return
        task_id = int(parts[2])
        try:
            data = validate_payload(self.read_json(), partial=True)
            data["updated_at"] = now_iso()
            assignments = ", ".join(f"{key} = :{key}" for key in data)
            with connect_db() as conn:
                cursor = conn.execute(f"UPDATE tasks SET {assignments} WHERE id = :id", {**data, "id": task_id})
                if cursor.rowcount == 0:
                    self.send_json({"error": "没有找到这条任务。"}, 404)
                    return
                row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            self.send_json({"task": serialize(row)})
        except ValueError as exc:
            self.send_json({"error": str(exc)}, 400)

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        parts = path.strip("/").split("/")
        if len(parts) != 3 or parts[:2] != ["api", "tasks"] or not parts[2].isdigit():
            self.send_json({"error": "接口不存在。"}, 404)
            return
        with connect_db() as conn:
            cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (int(parts[2]),))
        if cursor.rowcount == 0:
            self.send_json({"error": "没有找到这条任务。"}, 404)
        else:
            self.send_json({"deleted": True})

    def serve_static(self, requested: str) -> None:
        relative = "index.html" if requested in ("", "/") else requested.lstrip("/")
        candidate = (STATIC / relative).resolve()
        if not candidate.is_relative_to(STATIC.resolve()) or not candidate.is_file():
            self.send_json({"error": "页面不存在。"}, 404)
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

    def send_error(self, code: int, message: Optional[str] = None, explain: Optional[str] = None) -> None:
        if code in (400, 404, 405):
            self.send_json({"error": message or "请求无法处理。"}, code)
        else:
            super().send_error(code, message, explain)


def main() -> None:
    parser = argparse.ArgumentParser(description="AI 开发交付看板")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址；容器部署时用 0.0.0.0")
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()
    initialize_db()
    address = (args.host, args.port)
    server = ThreadingHTTPServer(address, Handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"AI 开发交付看板已启动：{url}")
    print(f"数据库：{DB_PATH}")
    if args.open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("正在停止服务…")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
