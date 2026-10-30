"""压缩 / 解压的主路径测试：用真实文件跑一遍往返（round-trip）。"""
from __future__ import annotations

import gzip
import tarfile
import zipfile
from pathlib import Path

import pytest

from zipkit.core.compress import entry_warnings, pack, pack_memory
from zipkit.core.extract import detect_kind, extract, list_archive
from zipkit.errors import ArchiveFormatError, ZipKitError


def test_pack_then_extract_roundtrip(sample_dir: Path, tmp_path: Path) -> None:
    """用户点名的 8 类文件：压缩后再解压，必须逐字节一致。"""
    sources = sorted(p for p in sample_dir.iterdir() if p.is_file())
    archive = tmp_path / "bundle.zip"

    report = pack(sources, out_path=archive)

    assert archive.exists()
    assert len(report.entries) == len(sources)
    assert report.total_in > 0
    assert 0 <= report.savings <= 0.99

    dest = tmp_path / "restored"
    result = extract(archive, dest=dest)
    assert result.kind == "zip"
    assert len(result.entries) == len(sources)

    for src in sources:
        target = dest / src.name
        assert target.exists(), f"{src.name} 没被解出来"
        assert target.read_bytes() == src.read_bytes(), f"{src.name} 内容被改动了"


def test_text_files_really_shrink(text_only_dir: Path, tmp_path: Path) -> None:
    """文本类应当有明显收益，并且不应该冒出"压不动"的警告。"""
    report = pack(sorted(text_only_dir.iterdir()), out_path=tmp_path / "texts.zip")
    assert report.savings > 0.3
    assert not any("压不动" in w for w in report.warnings)


def test_directory_input_keeps_structure(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (project / "README.md").write_text("# 项目\n", encoding="utf-8")

    archive = tmp_path / "project.zip"
    pack([project], out_path=archive)

    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
    assert "project/src/main.py" in names
    assert "project/README.md" in names


def test_pack_never_overwrites_existing_archive(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    src.write_text("内容\n", encoding="utf-8")
    target = tmp_path / "out.zip"

    first = pack([src], out_path=target)
    second = pack([src], out_path=target)

    assert first.out_path != second.out_path
    assert first.out_path.exists() and second.out_path.exists()


def test_empty_file_is_preserved(tmp_path: Path) -> None:
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    archive = tmp_path / "e.zip"

    report = pack([empty], out_path=archive)
    assert report.entries[0].size == 0
    assert any("0 字节" in w for w in report.warnings)

    dest = tmp_path / "out"
    extract(archive, dest=dest)
    assert (dest / "empty.txt").exists()
    assert (dest / "empty.txt").stat().st_size == 0


def test_gzip_roundtrip(text_only_dir: Path, tmp_path: Path) -> None:
    src = text_only_dir / "notes.txt"
    gz = tmp_path / "notes.txt.gz"
    gz.write_bytes(gzip.compress(src.read_bytes()))

    assert detect_kind(gz) == "gzip"
    dest = tmp_path / "gz-out"
    result = extract(gz, dest=dest)

    assert result.entries[0].name == "notes.txt"
    assert (dest / "notes.txt").read_bytes() == src.read_bytes()


def test_tar_gz_roundtrip(text_only_dir: Path, tmp_path: Path) -> None:
    tgz = tmp_path / "logs.tar.gz"
    with tarfile.open(tgz, "w:gz") as tf:
        tf.add(text_only_dir / "app.log", arcname="app.log")
        tf.add(text_only_dir / "data.csv", arcname="nested/data.csv")

    assert detect_kind(tgz) == "gzip"
    dest = tmp_path / "tgz-out"
    result = extract(tgz, dest=dest)

    assert (dest / "app.log").exists()
    assert (dest / "nested" / "data.csv").exists()
    assert len(result.entries) == 2


def test_7z_roundtrip(text_only_dir: Path, tmp_path: Path) -> None:
    py7zr = pytest.importorskip("py7zr", reason="未安装 py7zr，跳过 7z 测试")
    src = text_only_dir / "notes.txt"
    archive = tmp_path / "bundle.7z"

    with py7zr.SevenZipFile(str(archive), "w") as zf:
        zf.write(str(src), arcname="notes.txt")

    assert detect_kind(archive) == "7z"
    dest = tmp_path / "7z-out"
    result = extract(archive, dest=dest)

    assert result.kind == "7z"
    assert (dest / "notes.txt").read_bytes() == src.read_bytes()


def test_list_archive_does_not_extract(text_only_dir: Path, tmp_path: Path) -> None:
    archive = tmp_path / "l.zip"
    pack([text_only_dir / "notes.txt"], out_path=archive)

    info = list_archive(archive)
    assert info["kind"] == "zip"
    assert info["entries"][0]["name"] == "notes.txt"
    assert not (tmp_path / "notes.txt").exists()


def test_pack_memory_matches_disk_pack(text_only_dir: Path, tmp_path: Path) -> None:
    """网页版走的 pack_memory 必须和命令行给出同样的结果。"""
    payload = (text_only_dir / "notes.txt").read_bytes()
    blob, entries = pack_memory([("notes.txt", payload)], level="balanced")

    assert entries[0].name == "notes.txt"
    assert entries[0].size == len(payload)
    with zipfile.ZipFile(__import__("io").BytesIO(blob)) as zf:
        assert zf.read("notes.txt") == payload


def test_entry_warnings_mentions_hard_formats(tmp_path: Path) -> None:
    """BMP 这种本来就密的格式，收益低时必须提醒用户。"""
    import os

    bmp = tmp_path / "x.bmp"
    bmp.write_bytes(os.urandom(400_000))  # 随机字节：真正不可压缩
    report = pack([bmp], out_path=tmp_path / "x.zip")
    warnings = entry_warnings(report.entries)
    assert any("压不动" in w for w in warnings)


def test_missing_input_raises_friendly_error(tmp_path: Path) -> None:
    with pytest.raises(ZipKitError) as exc:
        pack([tmp_path / "不存在.txt"])
    assert "找不到" in exc.value.message


def test_unknown_format_is_reported(tmp_path: Path) -> None:
    fake = tmp_path / "fake.zip"
    fake.write_bytes(b"this is definitely not a zip file")
    with pytest.raises(ArchiveFormatError):
        detect_kind(fake)


def test_detect_kind_ignores_wrong_extension(tmp_path: Path) -> None:
    """把 zip 改名成 .dat 也要认出来（按魔数判断，不按扩展名）。"""
    archive = tmp_path / "real.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("a.txt", b"hello")
    disguised = tmp_path / "disguised.dat"
    disguised.write_bytes(archive.read_bytes())

    assert detect_kind(disguised) == "zip"


def test_extract_reports_progress(sample_dir: Path, tmp_path: Path) -> None:
    """图形界面靠这个回调画进度条，必须真的有数据、且总量对得上。"""
    sources = sorted(p for p in sample_dir.iterdir() if p.is_file())
    archive = tmp_path / "p.zip"
    pack(sources, out_path=archive)

    events = []
    dest = tmp_path / "out"
    extract(archive, dest=dest, progress=lambda name, done, total: events.append((name, done, total)))

    assert events, "没有收到任何进度回调"
    expected_total = sum(p.stat().st_size for p in sources)
    name, done, total = events[-1]
    assert total == expected_total
    assert done == total
