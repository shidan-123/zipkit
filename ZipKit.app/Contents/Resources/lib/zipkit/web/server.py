"""用标准库 http.server 搭的本地网页界面。

安全要点（这是本项目能被公开使用的底线）：
1. 默认只绑定 127.0.0.1，外部机器连不上；
2. 每次启动生成随机 token，页面带 token 才能调用 API（防别的网页跨站调用）；
3. 校验 Origin / Host，挡住 DNS rebinding；
4. 请求体有大小上限，避免一个请求把内存打满。
"""
from __future__ import annotations

import base64
import binascii
import io
import json
import secrets
import socket
import tempfile
import threading
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from ..core.compress import entry_warnings, pack_memory
from ..core.extract import extract as do_extract
from ..core.office import extract_text
from ..core.safety import DEFAULT_LIMITS, Limits, human
from ..errors import ZipKitError

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"


def _b64decode(data: str, field: str = "文件") -> bytes:
    try:
        return base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ZipKitError(f"{field}内容不是合法的 Base64", "这通常是浏览器传输出错，刷新页面重试") from exc


def _upload_name(name: str) -> str:
    """只取文件名，丢掉任何目录成分（防止服务端被写入奇怪路径）。"""
    cleaned = Path(str(name or "")).name.strip()
    return cleaned or "upload.bin"


class _Handler(BaseHTTPRequestHandler):
    server_version = "ZipKit"
    protocol_version = "HTTP/1.1"

    # 由 make_handler 注入
    token: str = ""
    max_upload: int = 64 * 1024 * 1024
    limits: Limits = DEFAULT_LIMITS

    # ---------------------------------------------------------- 基础工具
    def log_message(self, fmt: str, *args: Any) -> None:  # 不刷屏
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: Dict[str, Any], status: int = 200) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _error(self, status: int, message: str, hint: str = "") -> None:
        self._send_json({"error": message, "hint": hint}, status)

    # ---------------------------------------------------------- GET
    def do_GET(self) -> None:  # noqa: N802 (http.server 约定)
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            try:
                html = INDEX_FILE.read_bytes()
            except OSError:
                self._error(500, "找不到界面文件 index.html", "项目可能没解压完整，请重新下载")
                return
            self._send(200, html, "text/html; charset=utf-8")
            return
        if path == "/health":
            self._send_json({"ok": True})
            return
        self._error(404, "没有这个页面")

    # ---------------------------------------------------------- POST
    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path

        # 1) token：防止别的网站偷偷往本机发请求
        if self.headers.get("X-ZipKit-Token", "") != self.token:
            self._error(403, "请求缺少有效令牌", "请从终端里打印的那个地址打开页面，不要直接刷新收藏夹里的旧链接")
            return

        # 2) 长度上限
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._error(400, "Content-Length 不合法")
            return
        if length <= 0 or length > self.max_upload:
            self._error(
                413,
                f"请求太大（上限 {human(self.max_upload)}）",
                "压缩/解压大文件请用命令行：zipkit pack 文件名 或 zipkit unpack 文件名",
            )
            return

        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._error(400, "请求内容不是合法 JSON")
            return

        try:
            if path == "/api/pack":
                self._handle_pack(payload)
            elif path == "/api/unpack":
                self._handle_unpack(payload)
            elif path == "/api/text":
                self._handle_text(payload)
            else:
                self._error(404, "没有这个接口")
        except ZipKitError as exc:
            self._error(400, exc.message, exc.hint)
        except Exception as exc:  # 兜底，避免把 traceback 打到浏览器
            self._error(500, f"服务器内部错误：{exc!r}", "请把这个错误信息反馈到 GitHub Issues")

    # ---------------------------------------------------------- 压缩
    def _handle_pack(self, payload: Dict[str, Any]) -> None:
        items = payload.get("files") or []
        if not isinstance(items, list) or not items:
            self._error(400, "没有收到文件", "把文件拖进虚线框里再点开始压缩")
            return

        files = []
        for item in items:
            name = _upload_name(item.get("name"))
            data = _b64decode(item.get("data", ""), f"{name} ")
            if len(data) > self.max_upload:
                self._error(413, f"{name} 太大", "大文件请用命令行处理")
                return
            files.append((name, data))

        blob, entries = pack_memory(files, level=payload.get("level", "balanced"))
        total_in = sum(e.size for e in entries)
        savings = 1 - len(blob) / total_in if total_in else 0.0

        self._send_json(
            {
                "filename": "zipkit-打包.zip",
                "data": base64.b64encode(blob).decode("ascii"),
                "entries": [e.to_dict() for e in entries],
                "warnings": entry_warnings(entries),
                "total_in": total_in,
                "total_out": len(blob),
                "savings": round(savings, 4),
            }
        )

    # ---------------------------------------------------------- 解压
    def _handle_unpack(self, payload: Dict[str, Any]) -> None:
        name = _upload_name(payload.get("name"))
        data = _b64decode(payload.get("data", ""), name)

        with tempfile.TemporaryDirectory(prefix="zipkit-") as tmp:
            archive_path = Path(tmp) / name
            archive_path.write_bytes(data)
            dest = Path(tmp) / "unpacked"

            report = do_extract(archive_path, dest=dest, force=True, limits=self.limits)

            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for item in sorted(dest.rglob("*")):
                    if item.is_file():
                        zf.write(item, item.relative_to(dest).as_posix())
            blob = buf.getvalue()

        # 浏览器只能下载一个文件，所以把解压结果再打成一个 zip 交回去
        stem = name.rsplit(".", 1)[0] or "解压结果"
        self._send_json(
            {
                "filename": f"{stem}-解压结果.zip",
                "data": base64.b64encode(blob).decode("ascii"),
                "report": report.to_dict(),
            }
        )

    # ---------------------------------------------------------- 读文档
    def _handle_text(self, payload: Dict[str, Any]) -> None:
        name = _upload_name(payload.get("name"))
        data = _b64decode(payload.get("data", ""), name)

        with tempfile.TemporaryDirectory(prefix="zipkit-") as tmp:
            doc_path = Path(tmp) / name
            doc_path.write_bytes(data)
            text = extract_text(doc_path)

        self._send_json({"text": text, "chars": len(text)})


def _find_free_port(host: str, start: int, attempts: int = 20) -> int:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    raise ZipKitError(
        f"端口 {start}~{start + attempts} 都被占用了",
        "换一个端口试试：python -m zipkit web --port 9000",
    )


def create_server(
    host: str = "127.0.0.1", port: int = 8765, max_upload_mb: int = 64
) -> tuple:
    """创建（但不启动）服务，返回 (httpd, 访问地址)。便于测试与嵌入。"""
    token = secrets.token_urlsafe(16)
    port = _find_free_port(host, port)

    handler = type(
        "ZipKitHandler",
        (_Handler,),
        {
            "token": token,
            "max_upload": max_upload_mb * 1024 * 1024,
            "limits": Limits(
                max_total=max(DEFAULT_LIMITS.max_total, max_upload_mb * 1024 * 1024 * 8),
            ),
        },
    )

    httpd = ThreadingHTTPServer((host, port), handler)
    display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    actual_port = httpd.server_address[1]
    url = f"http://{display_host}:{actual_port}/?token={token}"
    return httpd, url


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    max_upload_mb: int = 64,
) -> int:
    """启动本地服务，阻塞直到用户按 Ctrl+C。"""
    httpd, url = create_server(host=host, port=port, max_upload_mb=max_upload_mb)

    print(
        "\n".join(
            [
                "",
                "  ╭──────────────────────────────────────────────╮",
                "  │  ZipKit 网页版已启动，在浏览器里操作即可      │",
                "  ╰──────────────────────────────────────────────╯",
                "",
                f"  地址：{url}",
                f"  只监听：{host}（外部机器无法访问）",
                f"  上传上限：{max_upload_mb} MB",
                "",
                "  关掉服务：在这个终端窗口按 Ctrl + C",
                "",
            ]
        )
    )

    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  服务已停止。")
    finally:
        httpd.server_close()
    return 0
