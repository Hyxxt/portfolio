"""Small, policy-aware HTTP and HTML helpers used by the workflow demo."""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser


APP_UA = "WorkflowAutomationDemo/1.0 (local, user-initiated)"
PAGE_TIMEOUT = 18


def parse_http_url(raw: str) -> str:
    value = raw.strip()
    parts = urllib.parse.urlsplit(value)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError(f"只支持有效的公开 HTTP/HTTPS 网址：{value}")
    if parts.port not in (None, 80, 443) or (parts.scheme.lower() == "http" and parts.port == 443) or (parts.scheme.lower() == "https" and parts.port == 80):
        raise ValueError("仅接受标准 HTTP/HTTPS 端口。")
    if parts.hostname.lower().endswith((".localhost", ".local", ".internal")):
        raise ValueError("仅支持公开网站，不支持本机或内网域名。")
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, ""))


def origin_of(url: str) -> tuple[str, str, int]:
    p = urllib.parse.urlsplit(url)
    return p.scheme.lower(), (p.hostname or "").lower(), p.port or (443 if p.scheme.lower() == "https" else 80)


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
        if not ipaddress.ip_address(address).is_global:
            raise ValueError("为保护本机安全，禁止访问私有、保留或本地 IP。")


def canonicalize(raw_url: str, base_url: str) -> str | None:
    try:
        return parse_http_url(urllib.parse.urljoin(base_url, raw_url.strip()))
    except ValueError:
        return None


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, origin: tuple[str, str, int]):
        super().__init__()
        self.origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = canonicalize(newurl, req.full_url)
        if target is None or origin_of(target) != self.origin:
            raise urllib.error.HTTPError(newurl, code, "跨域或非公开地址重定向已阻止", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, target)


def opener_for(origin: tuple[str, str, int]) -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(SafeRedirectHandler(origin))


def fetch_robots(origin: tuple[str, str, int]) -> tuple[urllib.robotparser.RobotFileParser | None, str]:
    scheme, host, port = origin
    hostpart = f"[{host}]" if ":" in host else host
    if port not in (80, 443):
        hostpart = f"{hostpart}:{port}"
    url = f"{scheme}://{hostpart}/robots.txt"
    parser = urllib.robotparser.RobotFileParser(url)
    req = urllib.request.Request(url, headers={"User-Agent": APP_UA, "Accept": "text/plain,*/*;q=0.1"})
    try:
        with opener_for(origin).open(req, timeout=10) as response:
            raw = response.read(512_001)
            if len(raw) > 512_000:
                return None, "robots.txt 超过 512 KB，已停止访问该站点。"
            charset = response.headers.get_content_charset() or "utf-8"
            parser.parse(raw.decode(charset, errors="replace").splitlines())
            return parser, ""
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 410):
            parser.parse([])
            return parser, ""
        return None, f"robots.txt 返回 HTTP {exc.code}，已跳过该站点。"
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return None, f"无法读取 robots.txt，已跳过该站点（{type(exc).__name__}）。"


class PageParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "iframe", "canvas", "nav", "footer", "header", "form"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title: list[str] = []
        self.h1: list[str] = []
        self.text: list[str] = []
        self.links: list[str] = []
        self.description = ""
        self.title_depth = 0
        self.h1_depth = 0
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        values = {k.lower(): (v or "") for k, v in attrs}
        if tag in self.SKIP:
            self.skip_depth += 1
        if tag == "title":
            self.title_depth += 1
        if tag == "h1":
            self.h1_depth += 1
        if tag == "meta":
            name = values.get("name", "").lower()
            prop = values.get("property", "").lower()
            if (name == "description" or prop == "og:description") and not self.description:
                self.description = values.get("content", "").strip()
        if tag == "a" and values.get("href") and "nofollow" not in values.get("rel", "").lower().split():
            self.links.append(values["href"])

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.SKIP and self.skip_depth:
            self.skip_depth -= 1
        if tag == "title" and self.title_depth:
            self.title_depth -= 1
        if tag == "h1" and self.h1_depth:
            self.h1_depth -= 1

    def handle_data(self, data):
        value = data.strip()
        if not value:
            return
        if self.title_depth:
            self.title.append(value)
        if self.h1_depth:
            self.h1.append(value)
        if not self.skip_depth:
            self.text.append(value)

    def result(self):
        import re
        return {
            "title": re.sub(r"\s+", " ", " ".join(self.title)).strip()[:500],
            "description": re.sub(r"\s+", " ", self.description).strip()[:1000],
            "h1": re.sub(r"\s+", " ", " ".join(self.h1)).strip()[:500],
            "text": re.sub(r"\s+", " ", " ".join(self.text)).strip()[:50_000],
            "links": self.links,
        }


def decode_page(raw: bytes, charset: str | None) -> str:
    for encoding in (charset, "utf-8", "gb18030"):
        if not encoding:
            continue
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            pass
    return raw.decode("utf-8", errors="replace")
