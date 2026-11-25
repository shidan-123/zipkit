#!/usr/bin/env python3
"""打包成独立程序时的 GUI 入口（Windows / macOS 通用）。

为什么要单独一个入口：
打包后的程序没有终端，任何异常都会"静默消失"。
这里把异常写进日志、并用系统原生弹窗告知用户。

- macOS：用 osascript 弹窗
- Windows：用 tkinter 的 messagebox（不依赖控制台）
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

LOG = Path.home() / "Library" / "Logs" / "ZipKit-crash.log"
if sys.platform.startswith("win"):
    LOG = Path.home() / "AppData" / "Local" / "ZipKit" / "crash.log"


def _notify(title: str, message: str) -> None:
    if sys.platform == "darwin":
        try:
            import subprocess

            script = (
                'display dialog "%s" with title "%s" buttons {"好"} '
                "default button 1 with icon caution"
                % (message.replace('"', "'"), title)
            )
            subprocess.run(
                ["/usr/bin/osascript", "-e", script],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except Exception:
            pass

    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        pass


def _report(exc: BaseException) -> None:
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        LOG.write_text(detail, encoding="utf-8")
    except Exception:
        pass

    _notify(
        "ZipKit",
        "启动失败：%s\n\n日志：%s" % (str(exc)[:300], LOG),
    )


def main() -> int:
    try:
        from zipkit.gui import main as gui_main

        return gui_main()
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - 打包后必须兜住所有异常
        _report(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
