#!/usr/bin/env python3
"""把 ZipKit.app 打成可直接上传到 GitHub Release 的 zip。

为什么不用 `zip -r`：
`zip` 会丢符号链接、丢可执行位，解压后双击就是"文件已损坏"。
macOS 自带 `ditto` 能保留资源叉、权限位和符号链接，是苹果官方推荐的打包方式。

用法：
    python3 scripts/package_release.py
产物：
    dist/ZipKit-<版本>-macos.zip
    dist/SHA256SUMS.txt
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "ZipKit.app"
DIST = ROOT / "dist"


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


def check_inputs() -> None:
    launcher = APP / "Contents" / "MacOS" / "ZipKit"
    plist = APP / "Contents" / "Info.plist"
    bundle_code = APP / "Contents" / "Resources" / "lib" / "zipkit" / "__init__.py"

    missing = [str(p) for p in (launcher, plist, bundle_code) if not p.exists()]
    if missing:
        raise SystemExit(
            "❌ 应用包不完整，先跑 `python3 scripts/build_app.py`：\n  " + "\n  ".join(missing)
        )
    if not (launcher.stat().st_mode & 0o111):
        raise SystemExit(f"❌ 启动器没有可执行位：{launcher}（chmod +x 后重试）")


def build_zip(target: Path) -> None:
    if sys.platform != "darwin" or shutil.which("ditto") is None:
        raise SystemExit("❌ 只有 macOS 能打这个包（需要 ditto）。在 macOS 上运行。")
    subprocess.run(
        ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(APP), str(target)],
        check=True,
    )


def verify_zip(target: Path) -> None:
    """解压前先确认：是合法 zip、包含启动器、启动器权限没丢。"""
    with zipfile.ZipFile(target) as archive:
        bad = archive.testzip()
        if bad:
            raise SystemExit(f"❌ 压缩包损坏，第一个坏文件：{bad}")

        names = set(archive.namelist())
        launcher = "ZipKit.app/Contents/MacOS/ZipKit"
        if launcher not in names:
            raise SystemExit(f"❌ 包里没有启动器：{launcher}")

        mode = (archive.getinfo(launcher).external_attr >> 16) & 0o777
        if not mode & 0o100:
            raise SystemExit(f"❌ 启动器丢了可执行位（mode={oct(mode)}）")

        count = len(names)
    print(f"✅ 校验通过：{count} 个条目，启动器权限 {oct(mode)}")


def main() -> int:
    version = project_version()
    check_inputs()
    DIST.mkdir(exist_ok=True)

    target = DIST / f"ZipKit-{version}-macos.zip"
    target.unlink(missing_ok=True)
    build_zip(target)
    verify_zip(target)

    digest = sha256(target)
    sums = DIST / "SHA256SUMS.txt"
    sums.write_text(f"{digest}  {target.name}\n", encoding="utf-8")

    size_mb = target.stat().st_size / 1024 / 1024
    print(f"📦 {target}  ({size_mb:.2f} MB)")
    print(f"🔑 sha256 {digest}")
    print(f"📄 校验文件 {sums}")
    print("\n下一步：把 dist/ 里的两个文件上传到 GitHub Release 即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
