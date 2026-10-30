#!/usr/bin/env python3
"""把 Python 代码打包进 ZipKit.app，让它不再依赖项目文件夹的位置。

为什么需要这一步：
macOS 从 Finder 启动的 App，如果没有隐私授权，**读不了 ~/Downloads、~/Documents、~/Desktop**。
项目放在这些目录里时，`import zipkit` 会直接抛 `PermissionError: Operation not permitted`。
把代码复制进 App 自己的 Resources 目录后，读取的是"应用自身的文件"，不受任何限制。

用法：python3 scripts/build_app.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "ZipKit.app"
LIB = APP / "Contents" / "Resources" / "lib"
LAUNCHER = APP / "Contents" / "MacOS" / "ZipKit"


def copy_package() -> int:
    """把 zipkit/ 包（含网页静态文件）复制到 App 内部。"""
    target = LIB / "zipkit"
    if target.exists():
        shutil.rmtree(target)

    shutil.copytree(
        ROOT / "zipkit",
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )

    # 顺手把版本文件写进去，方便确认打包版本
    (LIB / "BUNDLE_INFO.txt").write_text(
        f"built from {ROOT}\nversion file: zipkit/__init__.py\n",
        encoding="utf-8",
    )

    files = sum(1 for _ in target.rglob("*.py"))
    size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    print(f"✅ 已打包 {files} 个 .py 文件，共 {size / 1024:.1f} KB → {target}")
    return 0


def ensure_executable() -> None:
    if LAUNCHER.exists():
        LAUNCHER.chmod(0o755)


def build_icon() -> None:
    icon = APP / "Contents" / "Resources" / "AppIcon.icns"
    if icon.exists():
        print("✅ 图标已存在，跳过生成")
        return
    script = ROOT / "scripts" / "make_icon.py"
    if script.exists():
        subprocess.run([sys.executable, str(script)], check=False)


def main() -> int:
    if not APP.exists():
        print(f"❌ 找不到 {APP}", file=sys.stderr)
        return 1
    code = copy_package()
    ensure_executable()
    build_icon()

    # 自检：从任意目录导入，必须成功
    probe = subprocess.run(
        [sys.executable, "-c", "import zipkit, zipkit.gui; print(zipkit.__file__)"],
        env={"PYTHONPATH": str(LIB), "PATH": "/usr/bin:/bin"},
        cwd=tempfile.gettempdir(),   # 必须在别处跑，否则会误测到项目目录的副本
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        print("❌ 自检失败：\n" + probe.stderr, file=sys.stderr)
        return 1
    print(f"✅ 自检通过：{probe.stdout.strip()}")
    return code


if __name__ == "__main__":
    sys.exit(main())
