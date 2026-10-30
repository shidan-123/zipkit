"""安全测试：路径穿越、压缩炸弹、覆盖行为。

这些用例对应真实的攻击手法，每一条都值得单独存在——
因为它们一旦失守，用户只是"点了一下解压"，受害的可能是整台电脑。
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from zipkit.core.extract import extract
from zipkit.core.safety import Limits, safe_join, validate_member
from zipkit.errors import LimitsExceeded, UnsafeArchiveError


def _make_zip(path: Path, members: dict) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


# ---------------------------------------------------------------- 成员名检查
@pytest.mark.parametrize(
    "name",
    [
        "../evil.txt",
        "a/../../evil.txt",
        "..\\evil.txt",
        "/etc/passwd",
        "C:\\Windows\\evil.txt",
        "",
        ".",
        "dir/./../../x",
    ],
)
def test_validate_member_rejects_dangerous_names(name: str) -> None:
    with pytest.raises(UnsafeArchiveError):
        validate_member(name)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("notes.txt", "notes.txt"),
        ("./docs/a.txt", "docs/a.txt"),
        ("a//b/c.txt", "a/b/c.txt"),
        ("中文/报告.txt", "中文/报告.txt"),
    ],
)
def test_validate_member_accepts_normal_names(name: str, expected: str) -> None:
    assert validate_member(name) == expected


def test_safe_join_stays_inside(tmp_path: Path) -> None:
    target = safe_join(tmp_path, "a/b/c.txt")
    assert target == tmp_path.resolve() / "a" / "b" / "c.txt"


# ---------------------------------------------------------------- 路径穿越
def test_zip_slip_is_blocked(tmp_path: Path) -> None:
    evil = _make_zip(tmp_path / "evil.zip", {"../evil.txt": b"pwned"})
    dest = tmp_path / "out"

    with pytest.raises(UnsafeArchiveError):
        extract(evil, dest=dest)

    assert not (tmp_path / "evil.txt").exists()


def test_absolute_path_member_is_blocked(tmp_path: Path) -> None:
    evil = _make_zip(tmp_path / "abs.zip", {"C:/Windows/system32/evil.dll": b"pwned"})
    with pytest.raises(UnsafeArchiveError):
        extract(evil, dest=tmp_path / "out")


def test_nothing_is_written_when_a_member_is_dangerous(tmp_path: Path) -> None:
    """正常成员在前、恶意成员在后：也必须整体拒绝，不留半成品。"""
    evil = _make_zip(
        tmp_path / "mixed.zip",
        {"good.txt": b"ok", "../../evil.txt": b"pwned"},
    )
    dest = tmp_path / "out"

    with pytest.raises(UnsafeArchiveError):
        extract(evil, dest=dest)

    assert not dest.exists() or list(dest.iterdir()) == []


# ---------------------------------------------------------------- 压缩炸弹
def _write_bomb(path: Path, size_mb: int = 20) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("zeros.bin", b"\0" * (size_mb * 1024 * 1024))
    return path


def test_declared_size_limit(tmp_path: Path) -> None:
    bomb = _write_bomb(tmp_path / "bomb.zip")
    with pytest.raises(LimitsExceeded) as exc:
        extract(bomb, dest=tmp_path / "out", limits=Limits(max_total=1024 * 1024))
    assert "上限" in exc.value.message


def test_compression_ratio_limit(tmp_path: Path) -> None:
    """总量上限放宽后，压缩比这一层仍然要拦住。"""
    bomb = _write_bomb(tmp_path / "bomb.zip")
    relaxed = Limits(max_total=10 ** 9, max_single=10 ** 9, max_ratio=100)
    with pytest.raises(LimitsExceeded) as exc:
        extract(bomb, dest=tmp_path / "out", limits=relaxed)
    assert "压缩比" in exc.value.message


def test_file_count_limit(tmp_path: Path) -> None:
    archive = _make_zip(
        tmp_path / "many.zip", {f"f{i}.txt": b"x" for i in range(5)}
    )
    with pytest.raises(LimitsExceeded):
        extract(archive, dest=tmp_path / "out", limits=Limits(max_files=2))


# ---------------------------------------------------------------- 覆盖行为
def test_existing_files_are_renamed_by_default(tmp_path: Path) -> None:
    archive = _make_zip(tmp_path / "v1.zip", {"a.txt": b"v1"})
    dest = tmp_path / "out"

    extract(archive, dest=dest)
    extract(archive, dest=dest)

    assert (dest / "a.txt").read_bytes() == b"v1"
    assert (dest / "a (1).txt").read_bytes() == b"v1"


def test_force_overwrites_in_place(tmp_path: Path) -> None:
    dest = tmp_path / "out"
    dest.mkdir()
    (dest / "a.txt").write_bytes("旧内容".encode("utf-8"))

    archive = _make_zip(tmp_path / "v2.zip", {"a.txt": "新内容".encode("utf-8")})
    extract(archive, dest=dest, force=True)

    assert (dest / "a.txt").read_bytes() == "新内容".encode("utf-8")
