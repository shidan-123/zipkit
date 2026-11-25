#!/usr/bin/env python3
"""PyInstaller 的入口：打包成 macOS .app 时从这里启动。

单独写一个入口的原因是：
打包后的程序没有终端，任何异常都会“静默消失”。
所以这里把异常写进日志并用系统弹窗告诉用户，而不是让他双击后一脸茫然。
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

LOG = Path.home() / "Library" / "Logs" / "ZipKit-crash.log"


def _report(exc: BaseException) -> None:
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        LOG.write_text(detail, encoding="utf-8")
    except Exception:
        pass

    message = str(exc)[:300].replace('"', "'")
    script = (
        'display dialog "启动失败：%s\\n\\n日志：~/Library/Logs/ZipKit-crash.log" '
        'with title "ZipKit" buttons {"好"} default button 1 with icon caution' % message
    )
    try:
        import subprocess

        subprocess.run(["/usr/bin/osascript", "-e", script], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


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
