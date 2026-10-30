"""应用包与源码的一致性检查。

ZipKit.app 里放了一份代码副本（为了让 Finder 启动时不受目录权限限制）。
副本最容易出的问题就是"源码改了、包没重建"，这里用字节比对把它锁死。
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "zipkit"
BUNDLE = ROOT / "ZipKit.app" / "Contents" / "Resources" / "lib" / "zipkit"

pytestmark = pytest.mark.skipif(
    not BUNDLE.is_dir(),
    reason="应用包未构建，先执行 python3 scripts/build_app.py",
)


def _relative_files(base: Path):
    for path in sorted(base.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            yield path


def test_bundle_contains_all_files() -> None:
    missing = []
    for path in _relative_files(SOURCE):
        rel = path.relative_to(SOURCE)
        if not (BUNDLE / rel).exists():
            missing.append(str(rel))
    assert not missing, "应用包缺少文件（请重新构建）：" + "、".join(missing)


def test_bundle_is_not_stale() -> None:
    stale = []
    for path in _relative_files(SOURCE):
        rel = path.relative_to(SOURCE)
        bundled = BUNDLE / rel
        if bundled.exists() and bundled.read_bytes() != path.read_bytes():
            stale.append(str(rel))
    assert not stale, "应用包已过期（源码改了没重建）：" + "、".join(stale)


def test_bundle_has_entry_points() -> None:
    assert (BUNDLE / "gui.py").exists()
    assert (BUNDLE / "__main__.py").exists()
    assert (BUNDLE / "web" / "static" / "index.html").exists()
