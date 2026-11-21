from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import queue
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
STATIC = ROOT / "static"
DB_PATH = DATA / "automation.sqlite3"
MAX_SEEDS = 5
MAX_PAGES = 100
MAX_DEPTH = 3
REQUEST_DELAY = 1.5
MAX_BODY = 2_000_000

DATA.mkdir(exist_ok=True)
REPORTS.mkdir(exist_ok=True)
import crawler_core as crawler

WORK_QUEUE: queue.Queue[tuple[int, str]] = queue.Queue()
QUEUE_LOCK = threading.RLock()
QUEUED_TASKS: set[int] = set()
ACTIVE_RUN: dict[str, Any] = {"task_id": None, "run_id": None, "started_at": None}
EVENT_LOCK = threading.RLock()
EVENTS: list[dict[str, str]] = []
STOP_EVENT = threading.Event()


def now_local() -> datetime:
    return datetime.now().astimezone()


def stamp(value: datetime | None = None) -> str:
    return (value or now_local()).isoformat(timespec="seconds")


def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db() -> None:
    with db() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                seeds TEXT NOT NULL,
                max_pages INTEGER NOT NULL DEFAULT 20,
                max_depth INTEGER NOT NULL DEFAULT 1,
                interval_hours INTEGER NOT NULL DEFAULT 24,
                active INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                next_run_at TEXT,
                last_run_at TEXT
            );
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                task_id INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                pages_seen INTEGER NOT NULL DEFAULT 0,
                pages_ok INTEGER NOT NULL DEFAULT 0,
                changed_count INTEGER NOT NULL DEFAULT 0,
                duplicate_count INTEGER NOT NULL DEFAULT 0,
                error_count INTEGER NOT NULL DEFAULT 0,
                report_path TEXT,
                FOREIGN KEY(task_id) REFERENCES tasks(id)
            );
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                task_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                seed_url TEXT NOT NULL,
                depth INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                h1 TEXT NOT NULL DEFAULT '',
                body_text TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL DEFAULT '',
                change_type TEXT NOT NULL DEFAULT 'error',
                status_code INTEGER,
                error TEXT NOT NULL DEFAULT '',
                fetched_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES runs(id),
                FOREIGN KEY(task_id) REFERENCES tasks(id)
            );
            CREATE INDEX IF NOT EXISTS idx_snap_task_url ON snapshots(task_id,url,id DESC);
            CREATE INDEX IF NOT EXISTS idx_runs_task ON runs(task_id,started_at DESC);
            """
        )


def log(message: str, kind: str = "info") -> None:
    with EVENT_LOCK:
        EVENTS.append({"time": now_local().strftime("%H:%M:%S"), "message": message, "kind": kind})
        del EVENTS[:-120]


def local_origin_check(handler: BaseHTTPRequestHandler) -> bool:
    return handler.client_address[0] in {"127.0.0.1", "::1"}


def safe_seed_urls(raw: Any) -> list[str]:
    if isinstance(raw, str):
        values = raw.splitlines()
    elif isinstance(raw, list):
        values = [str(item) for item in raw]
    else:
        raise ValueError("请逐行填写 1 到 5 个公开网页网址。")
    seeds: list[str] = []
    for line in values:
        line = line.strip()
        if not line:
            continue
        url = crawler.parse_http_url(line)
        host = urllib.parse.urlsplit(url).hostname or ""
        crawler.assert_public_host(host)
        if url not in seeds:
            seeds.append(url)
    if not 1 <= len(seeds) <= MAX_SEEDS:
        raise ValueError(f"每个任务需要 1 到 {MAX_SEEDS} 个公开网址。")
    return seeds


def enqueue(task_id: int, reason: str) -> bool:
    with QUEUE_LOCK:
        if task_id in QUEUED_TASKS or ACTIVE_RUN.get("task_id") == task_id:
            return False
        with db() as con:
            task = con.execute("SELECT id FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not task:
            return False
        QUEUED_TASKS.add(task_id)
        WORK_QUEUE.put((task_id, reason))
    log(f"任务 #{task_id} 已进入队列（{reason}）。")
    return True


def schedule_loop() -> None:
    while not STOP_EVENT.wait(5):
        with db() as con:
            tasks = con.execute("SELECT id,next_run_at FROM tasks WHERE active=1 AND next_run_at IS NOT NULL").fetchall()
        now = now_local()
        for task in tasks:
            try:
                due = datetime.fromisoformat(task["next_run_at"])
            except (TypeError, ValueError):
                continue
            if due.tzinfo is None:
                due = due.astimezone()
            if due <= now:
                if enqueue(int(task["id"]), "定时调度"):
                    with db() as con:
                        row = con.execute("SELECT interval_hours FROM tasks WHERE id=?", (task["id"],)).fetchone()
                        interval = int(row["interval_hours"]) if row else 24
                        con.execute("UPDATE tasks SET next_run_at=? WHERE id=?", (stamp(now + timedelta(hours=interval)), task["id"]))


def fetch_page(url: str, origin: tuple[str, str, int]) -> dict[str, Any]:
    crawler.assert_public_host(origin[1])
    request = urllib.request.Request(url, headers={
        "User-Agent": crawler.APP_UA,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
    })
    started = time.monotonic()
    with crawler.opener_for(origin).open(request, timeout=crawler.PAGE_TIMEOUT) as response:
        code = response.status
        content_type = response.headers.get_content_type()
        if content_type not in {"text/html", "application/xhtml+xml"}:
            return {"status_code": code, "error": "非 HTML 内容，已跳过。", "elapsed_ms": round((time.monotonic()-started)*1000)}
        raw = response.read(MAX_BODY + 1)
        if len(raw) > MAX_BODY:
            return {"status_code": code, "error": "单页超过 2 MB 上限，已跳过。", "elapsed_ms": round((time.monotonic()-started)*1000)}
        markup = crawler.decode_page(raw, response.headers.get_content_charset())
        parser = crawler.PageParser()
        parser.feed(markup)
        parsed = parser.result()
        parsed["status_code"] = code
        parsed["error"] = ""
        parsed["elapsed_ms"] = round((time.monotonic()-started)*1000)
        return parsed


def fetch_snapshot(run_id: str, task_id: int, url: str, seed_url: str, depth: int) -> dict[str, Any]:
    origin = crawler.origin_of(url)
    record: dict[str, Any] = {
        "run_id": run_id, "task_id": task_id, "url": url, "seed_url": seed_url,
        "depth": depth, "title": "", "description": "", "h1": "", "body_text": "",
        "content_hash": "", "change_type": "error", "status_code": None, "error": "", "fetched_at": stamp(),
    }
    try:
        parsed = fetch_page(url, origin)
        record["status_code"] = parsed.get("status_code")
        record["error"] = parsed.get("error", "")
        for name in ("title", "description", "h1"):
            record[name] = parsed.get(name, "")
        record["body_text"] = parsed.get("text", "")
        record["_links"] = parsed.get("links", [])
        if not record["error"] and record["status_code"] and 200 <= record["status_code"] < 300:
            normalized = " ".join((record["title"] + " " + record["description"] + " " + record["body_text"]).split())
            record["content_hash"] = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    except urllib.error.HTTPError as exc:
        record["status_code"] = exc.code
        record["error"] = f"HTTP {exc.code}，停止尝试绕过访问限制。"
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        record["error"] = f"访问失败：{type(exc).__name__}"
    return record


def classify_change(con: sqlite3.Connection, record: dict[str, Any], run_hashes: dict[str, str]) -> str:
    if record["error"] or not record["content_hash"]:
        return "error"
    current_hash = record["content_hash"]
    if current_hash in run_hashes:
        return "duplicate"
    run_hashes[current_hash] = record["url"]
    previous = con.execute(
        "SELECT content_hash FROM snapshots WHERE task_id=? AND url=? AND content_hash<>'' ORDER BY id DESC LIMIT 1",
        (record["task_id"], record["url"]),
    ).fetchone()
    if not previous:
        return "new"
    return "same" if previous["content_hash"] == current_hash else "changed"


def write_report(run_id: str, task: sqlite3.Row, run_summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    report_path = REPORTS / f"run-{run_id}.md"
    lines = [
        f"# {task['name']} · 自动化巡检报告",
        "",
        f"- 任务编号：{task['id']}",
        f"- 运行编号：{run_id}",
        f"- 开始时间：{run_summary['started_at']}",
        f"- 结束时间：{run_summary['finished_at']}",
        f"- 页面处理：{run_summary['pages_seen']} 页；成功 {run_summary['pages_ok']} 页；异常 {run_summary['error_count']} 页",
        f"- 内容变化：新增/变化 {run_summary['changed_count']} 页；重复内容 {run_summary['duplicate_count']} 页",
        "",
        "## 页面变化",
        "",
    ]
    changes = [r for r in rows if r["change_type"] in {"new", "changed"}]
    if changes:
        for row in changes[:60]:
            lines.append(f"- **{row['change_type']}** · {row['title'] or '无标题'} · {row['url']}")
    else:
        lines.append("本次未发现新增或变化的成功页面。")
    errors = [r for r in rows if r["error"]]
    lines += ["", "## 异常记录", ""]
    if errors:
        for row in errors[:40]:
            lines.append(f"- {row['url']}：{row['error']}")
    else:
        lines.append("无。")
    lines += ["", "---", "报告由本地自动化任务生成；采集范围受 robots.txt、同源和请求间隔限制。", ""]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return str(report_path)


def run_task(task_id: int, reason: str) -> None:
    with db() as con:
        task = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not task:
        return
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    started_at = stamp()
    with db() as con:
        con.execute("INSERT INTO runs(id,task_id,started_at,status) VALUES(?,?,?,?)", (run_id, task_id, started_at, "running"))
    with QUEUE_LOCK:
        ACTIVE_RUN.update({"task_id": task_id, "run_id": run_id, "started_at": started_at})
    log(f"开始执行：{task['name']}（{reason}）。")
    seeds = json.loads(task["seeds"])
    origins = {crawler.origin_of(url) for url in seeds}
    robots_cache: dict[tuple[str, str, int], Any] = {}
    queue_items: list[tuple[str, str, int]] = [(url, url, 0) for url in seeds]
    queued_urls = {url for url, _, _ in queue_items}
    snapshots: list[dict[str, Any]] = []
    run_hashes: dict[str, str] = {}
    last_request: dict[tuple[str, str, int], float] = {}
    blocked: dict[tuple[str, str, int], str] = {}
    page_limit = min(int(task["max_pages"]), MAX_PAGES)
    depth_limit = min(int(task["max_depth"]), MAX_DEPTH)
    cursor = 0
    try:
        while cursor < len(queue_items) and len(snapshots) < page_limit:
            if STOP_EVENT.is_set():
                break
            url, seed_url, depth = queue_items[cursor]
            cursor += 1
            origin = crawler.origin_of(url)
            row = {
                "run_id": run_id, "task_id": task_id, "url": url, "seed_url": seed_url, "depth": depth,
                "title": "", "description": "", "h1": "", "body_text": "", "content_hash": "",
                "change_type": "error", "status_code": None, "error": "", "fetched_at": stamp(),
            }
            if origin not in origins:
                row["error"] = "跨同源链接已跳过。"
            elif origin in blocked:
                row["error"] = blocked[origin]
            else:
                if origin not in robots_cache:
                    robots, message = crawler.fetch_robots(origin)
                    robots_cache[origin] = robots
                    if message:
                        log(f"{origin[1]}：{message}", "warn")
                robots = robots_cache[origin]
                if robots is None:
                    row["error"] = "robots.txt 无法读取，按安全策略跳过。"
                elif not robots.can_fetch(crawler.APP_UA, url):
                    row["error"] = "robots.txt 禁止采集此路径。"
                else:
                    crawl_delay = robots.crawl_delay(crawler.APP_UA) or 0
                    request_rate = robots.request_rate(crawler.APP_UA)
                    if request_rate and request_rate.requests > 0:
                        crawl_delay = max(float(crawl_delay), request_rate.seconds / request_rate.requests)
                    wait = max(REQUEST_DELAY, float(crawl_delay))
                    prev = last_request.get(origin)
                    if prev is not None:
                        remaining = wait - (time.monotonic() - prev)
                        while remaining > 0 and not STOP_EVENT.is_set():
                            time.sleep(min(.25, remaining))
                            remaining = wait - (time.monotonic() - prev)
                    if STOP_EVENT.is_set():
                        break
                    last_request[origin] = time.monotonic()
                    row = fetch_snapshot(run_id, task_id, url, seed_url, depth)
                    row["fetched_at"] = stamp()
                    if row["status_code"] in (401, 403, 429):
                        blocked[origin] = f"站点返回 HTTP {row['status_code']}，已停止继续访问该站点。"
                        log(f"{origin[1]} 返回 HTTP {row['status_code']}，停止该站点任务。", "warn")
                    if row["content_hash"] and depth < depth_limit:
                        # Reparse only the HTML source on the next request? The parsed links are kept by PageParser,
                        # so fetch_snapshot stores them transiently for the queue below.
                        links = row.pop("_links", [])
                        for href in links:
                            target = crawler.canonicalize(href, url)
                            if target and crawler.origin_of(target) == origin and target not in queued_urls and len(queue_items) < 5_000:
                                queued_urls.add(target)
                                queue_items.append((target, seed_url, depth + 1))
            with db() as con:
                row["change_type"] = classify_change(con, row, run_hashes)
                con.execute(
                    """INSERT INTO snapshots
                    (run_id,task_id,url,seed_url,depth,title,description,h1,body_text,content_hash,change_type,status_code,error,fetched_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    tuple(row[k] for k in ("run_id","task_id","url","seed_url","depth","title","description","h1","body_text","content_hash","change_type","status_code","error","fetched_at")),
                )
            snapshots.append(row)
            label = row["title"] or url
            if row["error"]:
                log(f"跳过 {url}：{row['error']}", "warn")
            else:
                log(f"{row['change_type']} · {label}", "success" if row["change_type"] in {"new","changed"} else "info")
        status = "stopped" if STOP_EVENT.is_set() else "completed"
    except Exception as exc:
        status = "failed"
        log(f"任务异常停止：{type(exc).__name__}", "error")
    finished_at = stamp()
    ok = sum(1 for r in snapshots if r["content_hash"])
    changed = sum(1 for r in snapshots if r["change_type"] in {"new", "changed"})
    duplicates = sum(1 for r in snapshots if r["change_type"] == "duplicate")
    errors = sum(1 for r in snapshots if r["error"])
    summary = {
        "started_at": started_at, "finished_at": finished_at, "pages_seen": len(snapshots),
        "pages_ok": ok, "changed_count": changed, "duplicate_count": duplicates, "error_count": errors,
    }
    report_path = write_report(run_id, task, summary, snapshots)
    with db() as con:
        con.execute(
            "UPDATE runs SET finished_at=?,status=?,pages_seen=?,pages_ok=?,changed_count=?,duplicate_count=?,error_count=?,report_path=? WHERE id=?",
            (finished_at,status,len(snapshots),ok,changed,duplicates,errors,report_path,run_id),
        )
        con.execute("UPDATE tasks SET last_run_at=?,next_run_at=? WHERE id=?", (finished_at, stamp(now_local()+timedelta(hours=int(task["interval_hours"]))), task_id))
    with QUEUE_LOCK:
        ACTIVE_RUN.update({"task_id": None, "run_id": None, "started_at": None})
        QUEUED_TASKS.discard(task_id)
    log(f"报告已生成：处理 {len(snapshots)} 页，变化 {changed} 页，异常 {errors} 页。", "success")


def worker_loop() -> None:
    while not STOP_EVENT.is_set():
        try:
            task_id, reason = WORK_QUEUE.get(timeout=.5)
        except queue.Empty:
            continue
        try:
            run_task(task_id, reason)
        finally:
            with QUEUE_LOCK:
                QUEUED_TASKS.discard(task_id)
            WORK_QUEUE.task_done()


def task_rows() -> list[dict[str, Any]]:
    with db() as con:
        rows = con.execute(
            """SELECT t.*,
               (SELECT COUNT(*) FROM runs r WHERE r.task_id=t.id) AS run_count,
               (SELECT status FROM runs r WHERE r.task_id=t.id ORDER BY r.started_at DESC LIMIT 1) AS last_status
               FROM tasks t ORDER BY t.created_at DESC"""
        ).fetchall()
    output = []
    for r in rows:
        item = dict(r)
        item["seeds"] = json.loads(item["seeds"])
        item["queued"] = int(item["id"]) in QUEUED_TASKS
        item["running"] = ACTIVE_RUN.get("task_id") == int(item["id"])
        output.append(item)
    return output


def run_rows(limit: int = 30) -> list[dict[str, Any]]:
    with db() as con:
        rows = con.execute(
            "SELECT r.*,t.name AS task_name FROM runs r JOIN tasks t ON t.id=r.task_id ORDER BY r.started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def state_json() -> dict[str, Any]:
    with EVENT_LOCK:
        events = list(EVENTS)
    with QUEUE_LOCK:
        active = dict(ACTIVE_RUN)
        queued = len(QUEUED_TASKS)
    return {"tasks": task_rows(), "runs": run_rows(), "active_run": active, "queue_size": queued, "events": events}


def create_task(payload: dict[str, Any]) -> int:
    name = str(payload.get("name", "")).strip()[:60]
    if not name:
        raise ValueError("请填写任务名称。")
    seeds = safe_seed_urls(payload.get("seeds", ""))
    max_pages = int(payload.get("max_pages", 20))
    max_depth = int(payload.get("max_depth", 1))
    interval = int(payload.get("interval_hours", 24))
    if not 1 <= max_pages <= MAX_PAGES:
        raise ValueError(f"每次最多处理 {MAX_PAGES} 页。")
    if not 0 <= max_depth <= MAX_DEPTH:
        raise ValueError(f"采集深度范围为 0–{MAX_DEPTH}。")
    if not 1 <= interval <= 168:
        raise ValueError("自动运行间隔为 1–168 小时。")
    with db() as con:
        if con.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"] >= 30:
            raise ValueError("最多保存 30 个自动化任务。")
        cur = con.execute(
            "INSERT INTO tasks(name,seeds,max_pages,max_depth,interval_hours,active,created_at) VALUES(?,?,?,?,?,?,?)",
            (name,json.dumps(seeds,ensure_ascii=False),max_pages,max_depth,interval,0,stamp()),
        )
        task_id = int(cur.lastrowid)
    log(f"已创建任务：{name}（默认暂停，启动后可手动运行）。")
    return task_id


class Handler(BaseHTTPRequestHandler):
    server_version = "AutomationWorkbench/1.0"
    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def send_data(self, data: bytes, content_type: str, status: int = 200, filename: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers(); self.wfile.write(data)

    def send_json(self, value: Any, status: int = 200) -> None:
        self.send_data(json.dumps(value,ensure_ascii=False).encode("utf-8"),"application/json; charset=utf-8",status)

    def do_GET(self) -> None:
        if not local_origin_check(self):
            self.send_json({"error":"仅允许本机访问。"},403); return
        path = urllib.parse.urlsplit(self.path).path
        if path == "/": self.static("index.html","text/html; charset=utf-8")
        elif path == "/app.js": self.static("app.js","text/javascript; charset=utf-8")
        elif path == "/styles.css": self.static("styles.css","text/css; charset=utf-8")
        elif path == "/api/state": self.send_json(state_json())
        elif path.startswith("/api/report/"):
            run_id=path.rsplit("/",1)[-1]
            if not all(ch.isalnum() or ch == "-" for ch in run_id): self.send_json({"error":"报告编号无效。"},400); return
            with db() as con: row=con.execute("SELECT report_path FROM runs WHERE id=?",(run_id,)).fetchone()
            if not row or not row["report_path"] or not Path(row["report_path"]).is_file(): self.send_json({"error":"报告不存在。"},404); return
            self.send_data(Path(row["report_path"]).read_bytes(),"text/markdown; charset=utf-8",filename=f"report-{run_id}.md")
        elif path.startswith("/api/run/"):
            run_id=path.rsplit("/",1)[-1]
            with db() as con:
                run=con.execute("SELECT r.*,t.name AS task_name FROM runs r JOIN tasks t ON t.id=r.task_id WHERE r.id=?",(run_id,)).fetchone()
                pages=con.execute("SELECT url,title,depth,change_type,status_code,error,fetched_at FROM snapshots WHERE run_id=? ORDER BY id",(run_id,)).fetchall()
            if not run: self.send_json({"error":"任务记录不存在。"},404)
            else: self.send_json({"run":dict(run),"pages":[dict(row) for row in pages]})
        elif path == "/api/export":
            query=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query); run_id=query.get("run",[""])[0]; fmt=query.get("format",["csv"])[0]
            with db() as con: rows=con.execute("SELECT url,seed_url,depth,title,description,h1,body_text,content_hash,change_type,status_code,error,fetched_at FROM snapshots WHERE run_id=? ORDER BY id",(run_id,)).fetchall()
            data=[dict(row) for row in rows]
            if not data: self.send_json({"error":"没有可导出的记录。"},404)
            elif fmt=="json": self.send_data(json.dumps(data,ensure_ascii=False,indent=2).encode(),"application/json; charset=utf-8",filename=f"run-{run_id}.json")
            elif fmt=="csv":
                output=io.StringIO(newline=""); writer=csv.DictWriter(output,fieldnames=list(data[0].keys())); writer.writeheader(); writer.writerows(data)
                self.send_data(("\ufeff"+output.getvalue()).encode("utf-8"),"text/csv; charset=utf-8",filename=f"run-{run_id}.csv")
            else: self.send_json({"error":"仅支持 CSV 或 JSON。"},400)
        else: self.send_json({"error":"未找到该资源。"},404)

    def static(self,name: str,content_type: str) -> None:
        p=STATIC/name
        if not p.is_file(): self.send_json({"error":"静态页面缺失。"},404); return
        self.send_data(p.read_bytes(),content_type)

    def do_POST(self) -> None:
        if not local_origin_check(self): self.send_json({"error":"仅允许本机访问。"},403); return
        try:
            size=min(int(self.headers.get("Content-Length","0") or 0),100_000)
            payload=json.loads(self.rfile.read(size) or b"{}")
            if not isinstance(payload,dict): raise ValueError("请求格式无效。")
        except (ValueError,json.JSONDecodeError): self.send_json({"error":"请求内容无效。"},400); return
        path=urllib.parse.urlsplit(self.path).path
        try:
            if path=="/api/tasks": self.send_json({"ok":True,"id":create_task(payload)},201); return
            parts=path.strip("/").split("/")
            if len(parts)==4 and parts[0]=="api" and parts[1]=="tasks":
                task_id=int(parts[2]); action=parts[3]
                with db() as con: task=con.execute("SELECT * FROM tasks WHERE id=?",(task_id,)).fetchone()
                if not task: self.send_json({"error":"任务不存在。"},404); return
                if action=="run":
                    if not enqueue(task_id,"手动运行"): raise ValueError("该任务已在队列中或正在执行。")
                    self.send_json({"ok":True}); return
                if action=="toggle":
                    active=0 if task["active"] else 1
                    next_at=stamp(now_local()+timedelta(hours=int(task["interval_hours"]))) if active else None
                    with db() as con: con.execute("UPDATE tasks SET active=?,next_run_at=? WHERE id=?",(active,next_at,task_id))
                    log(f"任务 {task['name']} 已{'启用定时运行' if active else '暂停定时运行'}。")
                    self.send_json({"ok":True,"active":active}); return
            self.send_json({"error":"未找到该接口。"},404)
        except (ValueError,TypeError,OSError,sqlite3.Error) as exc: self.send_json({"error":str(exc)},400)


def main() -> None:
    init_db()
    threading.Thread(target=worker_loop,daemon=True,name="automation-worker").start()
    threading.Thread(target=schedule_loop,daemon=True,name="automation-scheduler").start()
    parser=argparse.ArgumentParser(description="本地自动化任务工作台")
    parser.add_argument("--host",default="127.0.0.1"); parser.add_argument("--port",type=int,default=8766)
    parser.add_argument("--open-browser",action="store_true")
    args=parser.parse_args()
    if args.host not in {"127.0.0.1","localhost","::1"}: raise SystemExit("只允许在本机启动。")
    server=ThreadingHTTPServer((args.host,args.port),Handler)
    url=f"http://127.0.0.1:{args.port}/"
    print(f"自动化工作台已启动：{url}")
    if args.open_browser: threading.Timer(.8,lambda:webbrowser.open(url)).start()
    try: server.serve_forever(poll_interval=.5)
    except KeyboardInterrupt: print("正在停止工作台……")
    finally:
        STOP_EVENT.set(); server.server_close()


if __name__=="__main__": main()
