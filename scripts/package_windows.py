#!/usr/bin/env python3
"""把 Windows 的两个 exe 打成发布用 zip。

为什么不用 PowerShell 的 Compress-Archive：
它在部分环境里处理中文文件名（`使用说明.txt`）会直接报错，
而且压缩结果不可复现。用标准库 zipfile 既跨平台又稳定，
还能在本机（macOS/Linux）先验证逻辑。

用法（在 Windows runner 上执行）：
    python scripts/package_windows.py
产物：
    dist/ZipKit-<版本>-windows-x64.zip
"""
from __future__ import annotations

import hashlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
README = ROOT / "packaging" / "使用说明.txt"
EXES = ("ZipKit.exe", "zipkit.exe")


def project_version() -> str:
    text = (ROOT / "zipkit" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("❌ 无法从 zipkit/__init__.py 读取 __version__")
    return match.group(1)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    version = project_version()

    missing = [name for name in EXES if not (DIST / name).exists()]
    if missing:
        raise SystemExit("❌ 缺少构建产物：" + "、".join(missing))
    if not README.exists():
        raise SystemExit(f"❌ 找不到说明文件：{README}")

    target = DIST / f"ZipKit-{version}-windows-x64.zip"
    target.unlink(missing_ok=True)

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in EXES:
            archive.write(DIST / name, arcname=name)
        archive.write(README, arcname="使用说明.txt")

    # 回读验证：三个文件都在，且 exe 非空
    with zipfile.ZipFile(target) as archive:
        bad = archive.testzip()
        if bad:
            raise SystemExit(f"❌ 压缩包损坏：{bad}")
        infos = {i.filename: i.file_size for i in archive.infolist()}

    for name in (*EXES, "使用说明.txt"):
        if name not in infos:
            raise SystemExit(f"❌ 压缩包里缺少 {name}")
        if name.endswith(".exe") and infos[name] < 1024 * 1024:
            raise SystemExit(f"❌ {name} 只有 {infos[name]} 字节，打包可能失败了")

    digest = sha256(target)
    sums = DIST / "SHA256-windows.txt"
    sums.write_text(f"{digest}  {target.name}\n", encoding="utf-8")

    print(f"📦 {target.name}  {target.stat().st_size / 1024 / 1024:.2f} MB")
    for name, size in infos.items():
        print(f"   · {name:<16} {size / 1024 / 1024:>6.2f} MB")
    print(f"🔑 sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
