#!/usr/bin/env python3
"""打包成独立程序时的命令行入口。

对应产物：Windows 的 `zipkit.exe`、macOS/Linux 的 `zipkit`。
普通用户双击 GUI 版就够了，这个给批处理、脚本、服务器用。
"""
from __future__ import annotations

import sys


def main() -> int:
    from zipkit.cli import main as cli_main

    return cli_main()


if __name__ == "__main__":
    sys.exit(main())
