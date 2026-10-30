"""命令行与网页接口的端到端测试。"""
from __future__ import annotations

import base64
import io
import json
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from zipkit.cli import main as cli_main


# ================================================================== 命令行
def test_cli_pack_and_unpack(text_only_dir: Path, tmp_path: Path, capsys) -> None:
    archive = tmp_path / "cli.zip"
    assert cli_main(["pack", str(text_only_dir / "notes.txt"), "-o", str(archive)]) == 0
    out = capsys.readouterr().out
    assert "已生成" in out
    assert archive.exists()

    dest = tmp_path / "cli-out"
    assert cli_main(["unpack", str(archive), "-d", str(dest)]) == 0
    assert (dest / "notes.txt").exists()


def test_cli_missing_file_exits_1(tmp_path: Path, capsys) -> None:
    assert cli_main(["pack", str(tmp_path / "nope.txt")]) == 1
    err = capsys.readouterr().err
    assert "找不到" in err
    assert "→" in err  # 必须带"该怎么办"的提示


def test_cli_check_outputs_estimate(text_only_dir: Path, capsys) -> None:
    assert cli_main(["check", str(text_only_dir / "notes.txt")]) == 0
    out = capsys.readouterr().out
    assert "预估可压缩" in out


def test_cli_list(text_only_dir: Path, tmp_path: Path, capsys) -> None:
    archive = tmp_path / "l.zip"
    cli_main(["pack", str(text_only_dir / "notes.txt"), "-o", str(archive)])
    capsys.readouterr()

    assert cli_main(["list", str(archive)]) == 0
    assert "notes.txt" in capsys.readouterr().out


def test_cli_text_command(office_dir: Path, capsys) -> None:
    assert cli_main(["text", str(office_dir / "report.docx")]) == 0
    assert "第一段" in capsys.readouterr().out


def test_cli_pack_json_mode(text_only_dir: Path, tmp_path: Path, capsys) -> None:
    archive = tmp_path / "j.zip"
    assert cli_main(["pack", str(text_only_dir / "notes.txt"), "-o", str(archive), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["entries"][0]["name"] == "notes.txt"


def test_cli_without_command_prints_banner(capsys) -> None:
    assert cli_main([]) == 0
    assert "ZipKit" in capsys.readouterr().out


# ================================================================== 网页版
@pytest.fixture
def web_server():
    from zipkit.web.server import create_server

    httpd, url = create_server(port=0, max_upload_mb=8)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd, url
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _base(httpd) -> str:
    return f"http://127.0.0.1:{httpd.server_address[1]}"


def _token(url: str) -> str:
    return parse_qs(urlparse(url).query)["token"][0]


def _post(url: str, payload: dict, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-ZipKit-Token"] = token
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(request, timeout=15) as resp:
        return resp.status, json.loads(resp.read())


def test_web_pack_then_unpack(web_server, text_only_dir: Path) -> None:
    httpd, url = web_server
    token = _token(url)
    payload = (text_only_dir / "notes.txt").read_bytes()

    status, data = _post(
        _base(httpd) + "/api/pack",
        {"level": "balanced", "files": [{"name": "notes.txt", "data": base64.b64encode(payload).decode()}]},
        token,
    )
    assert status == 200
    assert data["entries"][0]["name"] == "notes.txt"
    assert data["total_out"] < data["total_in"]

    blob = base64.b64decode(data["data"])
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        assert zf.read("notes.txt") == payload

    # 把刚生成的 zip 再传回去解压
    status, result = _post(
        _base(httpd) + "/api/unpack",
        {"name": "bundle.zip", "data": base64.b64encode(blob).decode()},
        token,
    )
    assert status == 200
    assert result["report"]["kind"] == "zip"
    unpacked = zipfile.ZipFile(io.BytesIO(base64.b64decode(result["data"])))
    assert unpacked.read("notes.txt") == payload


def test_web_requires_token(web_server) -> None:
    httpd, _ = web_server
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(_base(httpd) + "/api/pack", {"files": []})
    assert exc.value.code == 403


def test_web_health(web_server) -> None:
    httpd, _ = web_server
    with urllib.request.urlopen(_base(httpd) + "/health", timeout=5) as resp:
        assert json.loads(resp.read())["ok"] is True


def test_web_serves_ui(web_server) -> None:
    httpd, _ = web_server
    with urllib.request.urlopen(_base(httpd) + "/", timeout=5) as resp:
        html = resp.read().decode("utf-8")
    assert "ZipKit" in html
    assert "X-ZipKit-Token" in html  # 前端确实在传令牌


def test_web_text_endpoint(web_server, office_dir: Path) -> None:
    httpd, url = web_server
    token = _token(url)
    data = (office_dir / "report.docx").read_bytes()

    status, result = _post(
        _base(httpd) + "/api/text",
        {"name": "report.docx", "data": base64.b64encode(data).decode()},
        token,
    )
    assert status == 200
    assert "第一段" in result["text"]
