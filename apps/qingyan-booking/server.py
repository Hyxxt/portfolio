"""Local demo server for the Qingyan beauty salon booking assistant."""
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import os
import re
import sqlite3
import tempfile
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get("QINGYAN_DB_PATH", str(Path(tempfile.gettempdir()) / "qingyan-appointments.sqlite3")))
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
SERVICES = {
    "深层补水护理": {"duration": 60, "price": "¥198 起", "keywords": ["补水", "干燥", "缺水", "皮肤干", "有点干"]},
    "温和清洁护理": {"duration": 45, "price": "¥128 起", "keywords": ["清洁", "黑头", "毛孔"]},
    "初次肌肤咨询": {"duration": 30, "price": "免费", "keywords": ["咨询", "了解"]},
}

def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT NOT NULL,
        service TEXT NOT NULL, visit_date TEXT NOT NULL, visit_time TEXT NOT NULL,
        note TEXT DEFAULT '', status TEXT NOT NULL DEFAULT '待确认',
        created_at TEXT NOT NULL)""")
    return db

def answer(message):
    text = message.strip()
    if re.search(r"过敏|红肿|疼痛|不舒服|诊断|治疗|怀孕|受伤", text):
        return {"reply": "这类情况需要由专业人员判断，AI 不会替代诊断或建议继续护理。我已建议门店顾问尽快跟进；如果症状明显或持续，请及时咨询医疗专业人员。", "handoff": True}
    if re.search(r"价格|多少钱|收费|价钱", text):
        return {"reply": "目前门店参考价：深层补水护理 ¥198 起，温和清洁护理 ¥128 起，初次肌肤咨询免费。最终价格和适用项目请以到店顾问确认为准。", "handoff": False}
    if re.search(r"预约|时间|档期|营业|几点|哪天", text):
        return {"reply": "可以在页面右侧提交预约意向。可选时段为 10:30、13:00、15:30；提交后门店会人工确认，成功预约以门店回复为准。", "handoff": False}
    for name, service in SERVICES.items():
        if any(word in text for word in service["keywords"]):
            return {"reply": f"可以了解「{name}」，时长约 {service['duration']} 分钟，参考价 {service['price']}。每个人肤况不同，建议到店后由护理师确认是否适合。需要的话，可在预约表单中选择该项目。", "handoff": False}
    if re.search(r"项目|服务|做什么|推荐", text):
        return {"reply": "门店目前提供深层补水护理、温和清洁护理和初次肌肤咨询。你更想了解哪一项，或主要想改善什么问题？", "handoff": False}
    return {"reply": "我可以帮你了解门店项目、参考价格和预约方式。你可以告诉我关注补水、清洁，还是想先预约咨询。", "handoff": False}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = min(int(self.headers.get("Content-Length", "0")), 10000)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/appointments":
            with connect() as db:
                rows = db.execute("SELECT * FROM appointments ORDER BY visit_date, visit_time, id DESC").fetchall()
            return self.send_json(200, {"appointments": [dict(row) for row in rows]})
        if path == "/api/services":
            return self.send_json(200, {"services": [{"name": name, **info} for name, info in SERVICES.items()]})
        if path == "/" or path == "/index.html":
            file_path = ROOT / "index.html"
            content_type = "text/html; charset=utf-8"
        elif path in ("/styles.css", "/app.js"):
            file_path = ROOT / path.lstrip("/")
            content_type = "text/css; charset=utf-8" if path.endswith(".css") else "text/javascript; charset=utf-8"
        else:
            return self.send_json(404, {"error": "未找到"})
        try:
            data = file_path.read_bytes()
        except OSError:
            return self.send_json(404, {"error": "页面文件不存在"})
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            data = self.read_json()
        except (ValueError, json.JSONDecodeError):
            return self.send_json(400, {"error": "请求格式不正确"})
        if path == "/api/chat":
            message = str(data.get("message", ""))[:500].strip()
            if not message:
                return self.send_json(400, {"error": "请输入问题"})
            return self.send_json(200, answer(message))
        if path == "/api/appointments":
            name, phone = str(data.get("name", "")).strip(), str(data.get("phone", "")).strip()
            service, visit_date, visit_time = (str(data.get(key, "")).strip() for key in ("service", "date", "time"))
            note = str(data.get("note", "")).strip()[:300]
            if not name or len(name) > 30:
                return self.send_json(400, {"error": "请填写 1–30 个字的称呼"})
            if not re.fullmatch(r"1\d{10}", phone):
                return self.send_json(400, {"error": "请填写有效的 11 位手机号"})
            if service not in SERVICES:
                return self.send_json(400, {"error": "请选择有效服务项目"})
            try:
                chosen_date = date.fromisoformat(visit_date)
            except ValueError:
                return self.send_json(400, {"error": "请选择预约日期"})
            if chosen_date < date.today() or (chosen_date - date.today()).days > 90:
                return self.send_json(400, {"error": "预约日期需在今天至未来 90 天内"})
            if visit_time not in ("10:30", "13:00", "15:30"):
                return self.send_json(400, {"error": "请选择可预约时段"})
            with connect() as db:
                exists = db.execute("SELECT id FROM appointments WHERE visit_date=? AND visit_time=? AND status!='已取消'", (visit_date, visit_time)).fetchone()
                if exists:
                    return self.send_json(409, {"error": "这个时段已有预约意向，请换一个时间"})
                cursor = db.execute("INSERT INTO appointments (name,phone,service,visit_date,visit_time,note,status,created_at) VALUES (?,?,?,?,?,?,?,?)", (name, phone, service, visit_date, visit_time, note, "待确认", datetime.now().isoformat(timespec="minutes")))
                appointment_id = cursor.lastrowid
            return self.send_json(201, {"id": appointment_id, "message": "预约意向已提交，门店确认后会联系你。"})
        return self.send_json(404, {"error": "未找到"})

    def do_PATCH(self):
        match = re.fullmatch(r"/api/appointments/(\d+)", urlparse(self.path).path)
        if not match:
            return self.send_json(404, {"error": "未找到"})
        try:
            status = str(self.read_json().get("status", ""))
        except (ValueError, json.JSONDecodeError):
            return self.send_json(400, {"error": "请求格式不正确"})
        if status not in ("已确认", "已取消"):
            return self.send_json(400, {"error": "状态无效"})
        with connect() as db:
            result = db.execute("UPDATE appointments SET status=? WHERE id=?", (status, int(match.group(1))))
        if result.rowcount == 0:
            return self.send_json(404, {"error": "预约记录不存在"})
        return self.send_json(200, {"message": "预约状态已更新"})

if __name__ == "__main__":
    connect().close()
    print(f"轻颜 AI 预约助手已启动：http://{HOST}:{PORT}")
    print("本地演示数据存储在 appointments.sqlite3；按 Ctrl+C 停止。")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
