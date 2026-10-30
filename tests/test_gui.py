"""窗口版的构建测试。

两个坑：
1. 没有图形环境（CI/服务器）时必须跳过，不能让套件变红；
2. macOS 上 Tk 8.5 创建窗口会**直接 abort 进程**（连异常都抓不到），
   所以必须在创建之前按 TkVersion 跳过，而不是 try/except。
"""
from __future__ import annotations

import pytest

tkinter = pytest.importorskip("tkinter")

pytestmark = pytest.mark.skipif(
    tkinter.TkVersion < 8.6,
    reason=f"Tk {tkinter.TkVersion} 无法创建窗口（会 abort 进程），已跳过",
)


def _make_app():
    from zipkit.gui import ZipKitApp

    try:
        return ZipKitApp()
    except Exception as exc:  # 其他环境问题
        pytest.skip(f"当前环境无法创建窗口：{exc}")


def test_window_builds_and_closes() -> None:
    app = _make_app()
    try:
        app.update()
        assert "ZipKit" in app.title()
        assert app.winfo_width() > 400
        tabs = [app.tabs.tab(i, "text").strip() for i in range(app.tabs.index("end"))]
        assert tabs == ["压缩", "解压"]
    finally:
        app.destroy()


def test_adding_files_updates_summary(tmp_path) -> None:
    app = _make_app()
    try:
        sample = tmp_path / "a.txt"
        sample.write_text("hello", encoding="utf-8")
        app._pack_files.append(sample)
        app._refresh_file_list()

        assert app.file_list.size() == 1
        assert "1 项" in app.pack_summary.cget("text")
        assert str(sample.parent) in app.out_var.get()
    finally:
        app.destroy()


def test_cli_registers_gui_command() -> None:
    from zipkit.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["gui"])
    assert args.command == "gui"
    assert args.func.__name__ == "cmd_gui"


def test_old_tk_is_refused_early() -> None:
    """Tk 版本过低时，必须抛可读的错误，而不是让进程 abort。"""
    from zipkit import gui

    if tkinter.TkVersion >= 8.6:
        pytest.skip("本机 Tk 足够新，这条兜底逻辑没有触发条件")

    from zipkit.errors import ZipKitError

    with pytest.raises(ZipKitError) as exc:
        gui.main()
    assert "Tk" in exc.value.message
