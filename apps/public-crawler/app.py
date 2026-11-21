from __future__ import annotations

import argparse
import csv
import ipaddress
import io
import json
import os
import re
import socket
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.robotparser
import urllib.request
import webbrowser
from collections import deque
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


# 打包成 exe 后：静态资源在 PyInstaller 的临时解压目录里，
# 但 data 必须写在 exe 旁边，否则每次退出数据就没了。
if getattr(sys, "frozen", False):
    ROOT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    APP_DIR = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent
    APP_DIR = ROOT

# 公开演示模式：部署到 Render 等容器时设置 PUBLIC_DEMO=1。
ALLOW_REMOTE = os.environ.get("PUBLIC_DEMO") == "1"

STATIC = ROOT / "static"
DATA = APP_DIR / "data"
DB_PATH = DATA / "crawler.sqlite3"
APP_UA = "PublicWebCrawler/1.0 (local, user-initiated)"
MAX_BODY_BYTES = 2_000_000
MAX_TEXT_CHARS = 50_000
MAX_SEEDS = 20
MAX_PAGES_LIMIT = 500
ROBOTS_TIMEOUT = 10
PAGE_TIMEOUT = 18

DATA.mkdir(exist_ok=True)

STATE_LOCK = threading.RLock()
STATE: dict[str, Any] = {
    "running": False,
    "stop_requested": False,
    "run_id": None,
    "status": "idle",
    "started_at": None,
    "finished_at": None,
    "max_pages": 0,
    "max_depth": 0,
    "pages_seen": 0,
    "pages_ok": 0,
    "discovered": 0,
    "events": [],
}


def utc_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def connect_db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_db() -> None:
    with connect_db() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                seed_count INTEGER NOT NULL,
                max_pages INTEGER NOT NULL,
                max_depth INTEGER NOT NULL,
                delay_seconds REAL NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                url TEXT NOT NULL,
                seed_url TEXT NOT NULL,
                depth INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                h1 TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL DEFAULT '',
                status_code INTEGER,
                content_type TEXT NOT NULL DEFAULT '',
                bytes_read INTEGER NOT NULL DEFAULT 0,
                fetched_at TEXT NOT NULL,
                error TEXT NOT NULL DEFAULT '',
                UNIQUE(run_id, url),
                FOREIGN KEY(run_id) REFERENCES runs(id)
            );
            CREATE INDEX IF NOT EXISTS idx_pages_run_id ON pages(run_id, id DESC);
            """
        )


def event(message: str, kind: str = "info") -> None:
    record = {"time": datetime.now().astimezone().strftime("%H:%M:%S"), "message": message, "kind": kind}
    with STATE_LOCK:
        STATE["events"].append(record)
        STATE["events"] = STATE["events"][-180:]


def parse_http_url(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise ValueError("请填写至少一个网址。")
    parts = urllib.parse.urlsplit(value)
    if parts.scheme.lower() not in {"http", "https"}:
        raise ValueError(f"只支持 http 或 https 公开网页：{value}")
    if not parts.hostname or parts.username or parts.password:
        raise ValueError(f"网址格式无效：{value}")
    if parts.port not in (None, 80, 443) or (parts.scheme.lower() == "http" and parts.port == 443) or (parts.scheme.lower() == "https" and parts.port == 80):
        raise ValueError("为了减少误访问风险，仅接受标准 HTTP/HTTPS 端口。")
    if parts.hostname.lower().endswith((".localhost", ".local", ".internal")):
        raise ValueError("仅支持公开网站，不支持本机或内网域名。")
    path = parts.path or "/"
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def origin_of(url: str) -> tuple[str, str, int]:
    p = urllib.parse.urlsplit(url)
    return (p.scheme.lower(), (p.hostname or "").lower(), p.port or (443 if p.scheme.lower() == "https" else 80))


def assert_public_host(host: str) -> None:
    if host.lower() in {"localhost", "localhost.localdomain"}:
        raise ValueError("本地地址不在采集范围内。")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise ValueError(f"域名无法解析：{host}") from exc
    if not addresses:
        raise ValueError(f"域名无法解析：{host}")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("为保护本机安全，禁止访问私有、保留或本地 IP 地址。")


def canonicalize(raw_url: str, base_url: str | None = None) -> str | None:
    joined = urllib.parse.urljoin(base_url or "", raw_url.strip())
    try:
        return parse_http_url(joined)
    except ValueError:
        return None


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_origin: tuple[str, str, int]):
        super().__init__()
        self.allowed_origin = allowed_origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = canonicalize(newurl, req.full_url)
        if target is None or origin_of(target) != self.allowed_origin:
            raise urllib.error.HTTPError(newurl, code, "跨域或非公开地址重定向已阻止", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, target)


def opener_for(origin: tuple[str, str, int]) -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(SafeRedirectHandler(origin))


def fetch_robots(origin: tuple[str, str, int]) -> tuple[urllib.robotparser.RobotFileParser | None, str]:
    scheme, host, port = origin
    hostpart = f"[{host}]" if ":" in host else host
    if port not in (80, 443):
        hostpart = f"{hostpart}:{port}"
    robots_url = f"{scheme}://{hostpart}/robots.txt"
    parser = urllib.robotparser.RobotFileParser(robots_url)
    request = urllib.request.Request(robots_url, headers={"User-Agent": APP_UA, "Accept": "text/plain,*/*;q=0.1"})
    try:
        with opener_for(origin).open(request, timeout=ROBOTS_TIMEOUT) as response:
            raw = response.read(512_001)
            if len(raw) > 512_000:
                return None, "robots.txt 超过 512 KB，已停止访问该站点。"
            encoding = response.headers.get_content_charset() or "utf-8"
            parser.parse(raw.decode(encoding, errors="replace").splitlines())
            return parser, ""
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 410):
            parser.parse([])
            return parser, ""
        return None, f"robots.txt 返回 HTTP {exc.code}，已跳过该站点。"
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return None, f"无法读取 robots.txt，已跳过该站点（{type(exc).__name__}）。"


class PageParser(HTMLParser):
    SKIP_TAGS = {"script", "style", "noscript", "svg", "iframe", "canvas", "nav", "footer", "header", "form"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.h1_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[str] = []
        self.description = ""
        self.title_depth = 0
        self.h1_depth = 0
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        values = {k.lower(): (v or "") for k, v in attrs}
        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
        if tag == "title":
            self.title_depth += 1
        if tag == "h1":
            self.h1_depth += 1
        if tag == "meta":
            name = values.get("name", "").lower()
            prop = values.get("property", "").lower()
            if name == "description" or prop == "og:description":
                content = values.get("content", "").strip()
                if content and not self.description:
                    self.description = content
        if tag == "a" and values.get("href") and "nofollow" not in values.get("rel", "").lower().split():
            self.links.append(values["href"])

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        if tag == "title" and self.title_depth:
            self.title_depth -= 1
        if tag == "h1" and self.h1_depth:
            self.h1_depth -= 1

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if not value:
            return
        if self.title_depth:
            self.title_parts.append(value)
        if self.h1_depth:
            self.h1_parts.append(value)
        if not self.skip_depth:
            self.text_parts.append(value)

    def result(self) -> dict[str, Any]:
        text = re.sub(r"\s+", " ", " ".join(self.text_parts)).strip()[:MAX_TEXT_CHARS]
        return {
            "title": re.sub(r"\s+", " ", " ".join(self.title_parts)).strip()[:500],
            "description": re.sub(r"\s+", " ", self.description).strip()[:1_000],
            "h1": re.sub(r"\s+", " ", " ".join(self.h1_parts)).strip()[:500],
            "text": text,
            "links": self.links,
        }


def decode_page(raw: bytes, charset: str | None) -> str:
    candidates = [charset, "utf-8", "gb18030"]
    for encoding in candidates:
        if not encoding:
            continue
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def insert_page(record: dict[str, Any]) -> int:
    with connect_db() as con:
        cursor = con.execute(
            """INSERT OR REPLACE INTO pages
               (run_id,url,seed_url,depth,title,description,h1,text,status_code,content_type,bytes_read,fetched_at,error)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            tuple(record.get(key) for key in (
                "run_id", "url", "seed_url", "depth", "title", "description", "h1", "text",
                "status_code", "content_type", "bytes_read", "fetched_at", "error"
            )),
        )
        return int(cursor.lastrowid)


def update_run(run_id: str, status: str) -> None:
    with connect_db() as con:
        con.execute("UPDATE runs SET finished_at=?, status=? WHERE id=?", (utc_now(), status, run_id))
    with STATE_LOCK:
        STATE["running"] = False
        STATE["status"] = status
        STATE["finished_at"] = utc_now()
        STATE["stop_requested"] = False


def crawl_worker(run_id: str, seeds: list[str], max_pages: int, max_depth: int, user_delay: float) -> None:
    queue: deque[tuple[str, str, int]] = deque((url, url, 0) for url in seeds)
    visited: set[str] = set()
    queued: set[str] = set(seeds)
    robots: dict[tuple[str, str, int], urllib.robotparser.RobotFileParser | None] = {}
    host_last_request: dict[tuple[str, str, int], float] = {}
    blocked_origins: dict[tuple[str, str, int], str] = {}
    status = "completed"
    event(f"任务开始：{len(seeds)} 个种子网址，最多采集 {max_pages} 页。")
    try:
        while queue and len(visited) < max_pages:
            with STATE_LOCK:
                if STATE["stop_requested"]:
                    status = "stopped"
                    break
            url, seed_url, depth = queue.popleft()
            if url in visited:
                continue
            visited.add(url)
            origin = origin_of(url)
            if origin not in robots:
                parser, message = fetch_robots(origin)
                robots[origin] = parser
                if message:
                    event(f"跳过 {urllib.parse.urlsplit(url).netloc}：{message}", "warn")
            parser = robots[origin]
            record: dict[str, Any] = {
                "run_id": run_id, "url": url, "seed_url": seed_url, "depth": depth,
                "title": "", "description": "", "h1": "", "text": "", "status_code": None,
                "content_type": "", "bytes_read": 0, "fetched_at": utc_now(), "error": "",
            }
            if origin in blocked_origins:
                record["error"] = blocked_origins[origin]
            elif parser is None:
                record["error"] = "robots.txt 未能读取，按安全策略跳过。"
            elif not parser.can_fetch(APP_UA, url):
                record["error"] = "robots.txt 禁止采集此路径。"
                event(f"按 robots.txt 跳过：{url}", "warn")
            else:
                crawl_delay = parser.crawl_delay(APP_UA) or 0
                request_rate = parser.request_rate(APP_UA)
                if request_rate and request_rate.requests > 0:
                    crawl_delay = max(crawl_delay, request_rate.seconds / request_rate.requests)
                wait_for = max(user_delay, float(crawl_delay))
                previous = host_last_request.get(origin)
                if previous is not None:
                    remaining = wait_for - (time.monotonic() - previous)
                    while remaining > 0:
                        with STATE_LOCK:
                            if STATE["stop_requested"]:
                                status = "stopped"
                                break
                        time.sleep(min(remaining, 0.25))
                        remaining = wait_for - (time.monotonic() - previous)
                    if status == "stopped":
                        break
                with STATE_LOCK:
                    if STATE["stop_requested"]:
                        status = "stopped"
                        break
                host_last_request[origin] = time.monotonic()
                try:
                    assert_public_host(origin[1])
                    request = urllib.request.Request(url, headers={
                        "User-Agent": APP_UA,
                        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
                    })
                    started = time.monotonic()
                    with opener_for(origin).open(request, timeout=PAGE_TIMEOUT) as response:
                        record["status_code"] = response.status
                        record["content_type"] = response.headers.get_content_type()
                        if record["content_type"] not in {"text/html", "application/xhtml+xml"}:
                            record["error"] = "非 HTML 内容，已跳过。"
                        else:
                            raw = response.read(MAX_BODY_BYTES + 1)
                            record["bytes_read"] = len(raw)
                            if len(raw) > MAX_BODY_BYTES:
                                record["error"] = "页面超过 2 MB 上限，已跳过。"
                            else:
                                markup = decode_page(raw, response.headers.get_content_charset())
                                page_parser = PageParser()
                                page_parser.feed(markup)
                                extracted = page_parser.result()
                                for field in ("title", "description", "h1", "text"):
                                    record[field] = extracted[field]
                                record["elapsed_ms"] = round((time.monotonic() - started) * 1000)
                                if depth < max_depth:
                                    for href in extracted["links"]:
                                        link = canonicalize(href, url)
                                        if link and origin_of(link) == origin and link not in queued:
                                            if len(queue) < 10_000:
                                                queue.append((link, seed_url, depth + 1))
                                                queued.add(link)
                except urllib.error.HTTPError as exc:
                    record["status_code"] = exc.code
                    record["error"] = f"HTTP {exc.code}，未尝试绕过访问限制。"
                    if exc.code in (401, 403, 429):
                        blocked_origins[origin] = f"站点返回 HTTP {exc.code}，已停止继续访问该站点。"
                        event(f"收到 HTTP {exc.code}，停止访问 {origin[1]}。", "warn")
                except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                    record["error"] = f"访问失败：{type(exc).__name__}"
            insert_page(record)
            with STATE_LOCK:
                STATE["pages_seen"] += 1
                if record["status_code"] and 200 <= record["status_code"] < 300 and not record["error"]:
                    STATE["pages_ok"] += 1
                STATE["discovered"] = len(visited) + len(queue)
            if record["error"]:
                event(f"未采集：{url}（{record['error']}）", "warn")
            else:
                event(f"已采集：{record['title'] or url}")
        if status == "completed":
            event("任务完成：待采集队列已处理。", "success")
        else:
            event("已收到停止请求，当前页面处理完后停止。", "warn")
    except Exception as exc:  # Keep the local app responsive if one page triggers an unexpected parser/network error.
        status = "failed"
        event(f"任务遇到错误并停止：{type(exc).__name__}", "error")
    finally:
        update_run(run_id, status)


def start_crawl(payload: dict[str, Any]) -> None:
    raw_seeds = payload.get("seeds", "")
    if isinstance(raw_seeds, list):
        raw_seeds = "\n".join(str(item) for item in raw_seeds)
    seeds: list[str] = []
    for line in str(raw_seeds).splitlines():
        if not line.strip():
            continue
        url = parse_http_url(line)
        host = urllib.parse.urlsplit(url).hostname or ""
        assert_public_host(host)
        if url not in seeds:
            seeds.append(url)
    if not seeds:
        raise ValueError("请填写至少一个公开网页网址。")
    if len(seeds) > MAX_SEEDS:
        raise ValueError(f"单次最多支持 {MAX_SEEDS} 个种子网址。")
    max_pages = int(payload.get("max_pages", 100))
    max_depth = int(payload.get("max_depth", 2))
    delay = float(payload.get("delay_seconds", 1.5))
    if not 1 <= max_pages <= MAX_PAGES_LIMIT:
        raise ValueError(f"页数范围为 1–{MAX_PAGES_LIMIT}。")
    if not 0 <= max_depth <= 5:
        raise ValueError("采集深度范围为 0–5。")
    if not 1.0 <= delay <= 30.0:
        raise ValueError("每页间隔范围为 1–30 秒。")
    with STATE_LOCK:
        if STATE["running"]:
            raise ValueError("已有采集任务正在运行。")
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        STATE.update({
            "running": True, "stop_requested": False, "run_id": run_id, "status": "running",
            "started_at": utc_now(), "finished_at": None, "max_pages": max_pages, "max_depth": max_depth,
            "pages_seen": 0, "pages_ok": 0, "discovered": len(seeds), "events": [],
        })
    with connect_db() as con:
        con.execute(
            "INSERT INTO runs (id,started_at,seed_count,max_pages,max_depth,delay_seconds,status) VALUES (?,?,?,?,?,?,?)",
            (run_id, utc_now(), len(seeds), max_pages, max_depth, delay, "running"),
        )
    thread = threading.Thread(target=crawl_worker, args=(run_id, seeds, max_pages, max_depth, delay), daemon=True)
    thread.start()


def current_run_id() -> str | None:
    with STATE_LOCK:
        active = STATE.get("run_id")
    if active:
        return active
    with connect_db() as con:
        row = con.execute("SELECT id FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()
    return row["id"] if row else None


def page_summaries(run_id: str | None) -> list[dict[str, Any]]:
    if not run_id:
        return []
    with connect_db() as con:
        rows = con.execute(
            "SELECT id,url,seed_url,depth,title,description,h1,text,status_code,content_type,bytes_read,fetched_at,error "
            "FROM pages WHERE run_id=? ORDER BY id DESC LIMIT 500", (run_id,)
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["preview"] = item.pop("text")[:360]
        result.append(item)
    return result


def state_payload() -> dict[str, Any]:
    with STATE_LOCK:
        data = {key: value for key, value in STATE.items() if key != "stop_requested"}
        data["events"] = list(STATE["events"])
    data["run_id"] = data.get("run_id") or current_run_id()
    if not data.get("started_at") and data["run_id"]:
        with connect_db() as con:
            row = con.execute("SELECT * FROM runs WHERE id=?", (data["run_id"],)).fetchone()
            if row:
                data["status"] = row["status"]
                data["started_at"] = row["started_at"]
                data["finished_at"] = row["finished_at"]
                data["max_pages"] = row["max_pages"]
                data["max_depth"] = row["max_depth"]
    data["results"] = page_summaries(data["run_id"])
    if data.get("run_id") and not data.get("running"):
        data["pages_seen"] = len(data["results"])
        data["pages_ok"] = sum(1 for row in data["results"] if row["status_code"] and 200 <= row["status_code"] < 300 and not row["error"])
    return data


def export_rows(run_id: str) -> list[dict[str, Any]]:
    with connect_db() as con:
        rows = con.execute(
            "SELECT url,seed_url,depth,title,description,h1,text,status_code,content_type,bytes_read,fetched_at,error "
            "FROM pages WHERE run_id=? ORDER BY id", (run_id,)
        ).fetchall()
    return [dict(row) for row in rows]


class Handler(BaseHTTPRequestHandler):
    server_version = "PublicWebCrawler/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def send_bytes(self, data: bytes, content_type: str, status: int = 200, filename: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_bytes(body, "application/json; charset=utf-8", status)

    def do_GET(self) -> None:
        if not ALLOW_REMOTE and self.client_address[0] not in {"127.0.0.1", "::1"}:
            self.send_json({"error": "仅允许本机访问。"}, 403)
            return
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/":
            self.serve_static("index.html", "text/html; charset=utf-8")
        elif parsed.path == "/app.js":
            self.serve_static("app.js", "text/javascript; charset=utf-8")
        elif parsed.path == "/styles.css":
            self.serve_static("styles.css", "text/css; charset=utf-8")
        elif parsed.path == "/api/state":
            self.send_json(state_payload())
        elif parsed.path.startswith("/api/page/"):
            try:
                page_id = int(parsed.path.rsplit("/", 1)[1])
            except ValueError:
                self.send_json({"error": "页面编号无效。"}, 400)
                return
            with connect_db() as con:
                row = con.execute("SELECT * FROM pages WHERE id=?", (page_id,)).fetchone()
            self.send_json(dict(row) if row else {"error": "页面不存在。"}, 200 if row else 404)
        elif parsed.path == "/api/export":
            run_id = current_run_id()
            if not run_id:
                self.send_json({"error": "还没有可导出的采集结果。"}, 404)
                return
            rows = export_rows(run_id)
            fmt = urllib.parse.parse_qs(parsed.query).get("format", ["csv"])[0].lower()
            if fmt == "json":
                body = json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")
                self.send_bytes(body, "application/json; charset=utf-8", filename=f"crawler-{run_id}.json")
            elif fmt == "csv":
                output = io.StringIO(newline="")
                if rows:
                    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()), extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(rows)
                body = ("\ufeff" + output.getvalue()).encode("utf-8")
                self.send_bytes(body, "text/csv; charset=utf-8", filename=f"crawler-{run_id}.csv")
            else:
                self.send_json({"error": "导出格式仅支持 CSV 或 JSON。"}, 400)
        else:
            self.send_json({"error": "未找到该资源。"}, 404)

    def serve_static(self, name: str, content_type: str) -> None:
        path = STATIC / name
        if not path.is_file():
            self.send_json({"error": "静态资源缺失。"}, 404)
            return
        self.send_bytes(path.read_bytes(), content_type)

    def do_POST(self) -> None:
        if not ALLOW_REMOTE and self.client_address[0] not in {"127.0.0.1", "::1"}:
            self.send_json({"error": "仅允许本机访问。"}, 403)
            return
        length = min(int(self.headers.get("Content-Length", "0") or 0), 100_000)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_json({"error": "请求内容不是有效 JSON。"}, 400)
            return
        if self.path == "/api/start":
            try:
                start_crawl(payload)
                self.send_json({"ok": True})
            except (ValueError, TypeError, OSError) as exc:
                self.send_json({"error": str(exc)}, 400)
        elif self.path == "/api/stop":
            with STATE_LOCK:
                if STATE["running"]:
                    STATE["stop_requested"] = True
                    event("已请求停止；当前请求结束后将停止。", "warn")
            self.send_json({"ok": True})
        else:
            self.send_json({"error": "未找到该接口。"}, 404)


def main() -> None:
    init_db()
    cli = argparse.ArgumentParser(description="本地公开网页采集器")
    cli.add_argument("--host", default="127.0.0.1", help="服务监听地址，默认仅本机")
    cli.add_argument("--port", type=int, default=8765)
    cli.add_argument("--open-browser", action="store_true", help="启动后打开本地界面")
    args = cli.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"} and not ALLOW_REMOTE:
        raise SystemExit("出于安全考虑，界面只监听本机回环地址；容器部署请设置 PUBLIC_DEMO=1。")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    address = f"http://127.0.0.1:{args.port}/"
    print(f"公开网页采集器已启动：{address}")
    print("按 Ctrl+C 停止服务。采集范围：robots.txt 允许、同源、公开 HTML 页面。")
    if args.open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(address)).start()
    try:
        server.serve_forever(poll_interval=0.4)
    except KeyboardInterrupt:
        print("正在关闭本地服务……")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
