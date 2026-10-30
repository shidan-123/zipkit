"""Office 文档：结构解包 + 正文提取。"""
from __future__ import annotations

from pathlib import Path

import pytest

from zipkit.core.extract import extract
from zipkit.core.office import extract_text, list_parts
from zipkit.errors import ArchiveFormatError, ZipKitError


def test_docx_text(office_dir: Path) -> None:
    text = extract_text(office_dir / "report.docx")
    assert "ZipKit 测试文档" in text
    assert "第一段" in text
    assert "张三" in text  # 表格里的文字也要能取到


def test_xlsx_text(office_dir: Path) -> None:
    text = extract_text(office_dir / "grades.xlsx")
    assert "成绩表" in text          # 工作表名
    assert "张三" in text
    assert "95" in text
    assert "李四" in text


def test_pptx_text(office_dir: Path) -> None:
    text = extract_text(office_dir / "deck.pptx")
    assert "第一页标题" in text
    assert "第二页正文内容" in text
    assert "## 第 2 页" in text


def test_list_parts_shows_zip_nature(office_dir: Path) -> None:
    parts = [p["name"] for p in list_parts(office_dir / "report.docx")]
    assert "word/document.xml" in parts
    assert "[Content_Types].xml" in parts


def test_extract_docx_unpacks_xml(office_dir: Path, tmp_path: Path) -> None:
    """"解压 docx" 的真实效果：得到 XML，并且必须给出提醒。"""
    dest = tmp_path / "unpacked"
    report = extract(office_dir / "report.docx", dest=dest)

    assert report.kind == "ooxml"
    assert (dest / "word" / "document.xml").exists()
    assert any("本质是 ZIP" in w for w in report.warnings)


def test_corrupt_docx_is_reported(tmp_path: Path) -> None:
    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"this is not a zip at all")
    with pytest.raises(ArchiveFormatError) as exc:
        extract_text(broken)
    assert "损坏" in exc.value.message


def test_non_office_suffix_is_rejected(tmp_path: Path) -> None:
    txt = tmp_path / "a.txt"
    txt.write_text("hello", encoding="utf-8")
    with pytest.raises(ZipKitError) as exc:
        extract_text(txt)
    assert "不是 Office 文档" in exc.value.message


def test_bad_7z_style_document_reports_clearly(tmp_path: Path) -> None:
    """空文件伪装成 docx：要给出"已损坏"而不是崩掉堆栈。"""
    empty = tmp_path / "empty.docx"
    empty.write_bytes(b"")
    with pytest.raises(ArchiveFormatError):
        extract_text(empty)
