"""Office 文档（.docx / .xlsx / .pptx）的正文提取。

为什么需要这个模块：
用户想要"解压 docx"，但解压出来的是 `word/document.xml` 这种 XML —— 对普通人没用，
而且一旦有人试图改完再压回去，文档有概率彻底打不开。
真正有用的操作是"把里面的文字读出来"，所以这里单独提供 `extract_text()`。
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Iterator, List
from xml.etree import ElementTree as ET

from ..errors import ArchiveFormatError, ZipKitError
from .formats import OOXML_EXTS, suffix_of

MAX_CHARS = 2_000_000  # 单次最多导出 200 万字符，避免把终端刷爆


def _local(tag: str) -> str:
    """去掉 XML 命名空间，只留标签名：{...}t -> t。"""
    return tag.rsplit("}", 1)[-1]


def _open(path: Path) -> zipfile.ZipFile:
    if suffix_of(path) not in OOXML_EXTS:
        raise ZipKitError(
            f"不是 Office 文档：{path.name}",
            "本功能只处理 .docx / .xlsx / .pptx；要解压普通压缩包请用 `zipkit unpack`",
        )
    try:
        return zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ArchiveFormatError(
            f"这个 Office 文件已损坏（不是合法 ZIP）：{exc}",
            "常见原因：下载中断、被邮件网关改动、或其实是老版 .doc/.xls/.ppt（请先另存为新格式）",
        ) from exc


def list_parts(path: Path | str) -> List[dict]:
    """列出文档内部结构，让人看到"这是个 ZIP"这件事。"""
    p = Path(path).expanduser()
    with _open(p) as zf:
        return [
            {"name": i.filename, "size": i.file_size, "compressed": i.compress_size}
            for i in zf.infolist()
            if not i.is_dir()
        ]


def extract_text(path: Path | str, max_chars: int = MAX_CHARS) -> str:
    """按扩展名分派到对应的解析器，返回纯文本。"""
    p = Path(path).expanduser()
    suffix = suffix_of(p)
    with _open(p) as zf:
        names = set(zf.namelist())
        if suffix == ".docx":
            text = _docx_text(zf, names)
        elif suffix == ".xlsx":
            text = _xlsx_text(zf, names)
        elif suffix == ".pptx":
            text = _pptx_text(zf, names)
        else:  # pragma: no cover
            raise ZipKitError(f"不支持的 Office 类型：{suffix}")
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n…（已截断，只显示前 {max_chars} 个字符）"
    return text


# ------------------------------------------------------------------ DOCX
def _docx_text(zf: zipfile.ZipFile, names: set) -> str:
    part = "word/document.xml"
    if part not in names:
        raise ArchiveFormatError("找不到 word/document.xml，可能不是 .docx", "确认文件后缀与实际内容一致")
    root = ET.fromstring(zf.read(part))
    lines: List[str] = []

    for paragraph in root.iter():
        if _local(paragraph.tag) != "p":
            continue
        buf: List[str] = []
        for node in paragraph.iter():
            tag = _local(node.tag)
            if tag == "t" and node.text:
                buf.append(node.text)
            elif tag == "tab":
                buf.append("\t")
            elif tag in ("br", "cr"):
                buf.append("\n")
        line = "".join(buf).strip()
        if line:
            lines.append(line)

    return "\n".join(lines)


# ------------------------------------------------------------------ XLSX
def _xlsx_shared_strings(zf: zipfile.ZipFile, names: set) -> List[str]:
    if "xl/sharedStrings.xml" not in names:
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    out: List[str] = []
    for si in root.iter():
        if _local(si.tag) != "si":
            continue
        out.append("".join(t.text or "" for t in si.iter() if _local(t.tag) == "t"))
    return out


def _xlsx_sheet_names(zf: zipfile.ZipFile, names: set) -> List[tuple]:
    """返回 [(显示名, 内部 xml 路径)]，顺序与 Excel 里看到的一致。"""
    if "xl/workbook.xml" not in names:
        return []
    sheet_targets: dict = {}
    if "xl/_rels/workbook.xml.rels" in names:
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        for rel in rels:
            rid = rel.get("Id")
            target = rel.get("Target", "")
            if rid and target:
                sheet_targets[rid] = target.lstrip("/")

    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    result: List[tuple] = []
    for node in workbook.iter():
        if _local(node.tag) != "sheet":
            continue
        title = node.get("name") or "Sheet"
        rid = next((v for k, v in node.attrib.items() if _local(k) == "id"), None)
        target = sheet_targets.get(rid) if rid else None
        if target is None:
            result.append((title, ""))
        else:
            result.append((title, target if target.startswith("xl/") else f"xl/{target}"))
    return result


def _xlsx_text(zf: zipfile.ZipFile, names: set) -> str:
    shared = _xlsx_shared_strings(zf, names)
    sheets = _xlsx_sheet_names(zf, names)

    if not sheets:
        # 兜底：没有 workbook 关系时按文件名顺序读
        sheets = [
            (Path(n).stem, n)
            for n in sorted(names)
            if n.startswith("xl/worksheets/") and n.endswith(".xml")
        ]

    blocks: List[str] = []
    for title, part in sheets:
        if not part or part not in names:
            continue
        blocks.append(f"## 工作表：{title}")
        root = ET.fromstring(zf.read(part))
        for row in root.iter():
            if _local(row.tag) != "row":
                continue
            cells: List[str] = []
            for cell in row:
                if _local(cell.tag) != "c":
                    continue
                cells.append(_cell_value(cell, shared))
            if any(c.strip() for c in cells):
                blocks.append("\t".join(cells))
        blocks.append("")
    return "\n".join(blocks).strip()


def _cell_value(cell, shared: List[str]) -> str:
    ctype = cell.get("t")
    raw_v = ""
    inline = ""
    for child in cell:
        tag = _local(child.tag)
        if tag == "v":
            raw_v = child.text or ""
        elif tag == "is":
            inline = "".join(t.text or "" for t in child.iter() if _local(t.tag) == "t")

    if ctype == "s":
        try:
            return shared[int(raw_v)]
        except (ValueError, IndexError):
            return raw_v
    if ctype == "inlineStr":
        return inline
    if ctype == "b":
        return "TRUE" if raw_v == "1" else "FALSE"
    return raw_v


# ------------------------------------------------------------------ PPTX
def _slide_sort_key(name: str) -> int:
    match = re.search(r"slide(\d+)\.xml$", name)
    return int(match.group(1)) if match else 0


def _pptx_text(zf: zipfile.ZipFile, names: set) -> str:
    slides = sorted(
        (n for n in names if n.startswith("ppt/slides/slide") and n.endswith(".xml")),
        key=_slide_sort_key,
    )
    if not slides:
        raise ArchiveFormatError("这个 pptx 里没有幻灯片", "文件可能已损坏，或其实是别的格式")

    blocks: List[str] = []
    for index, name in enumerate(slides, start=1):
        root = ET.fromstring(zf.read(name))
        texts = [t.text for t in root.iter() if _local(t.tag) == "t" and t.text]
        if not texts:
            continue
        blocks.append(f"## 第 {index} 页")
        blocks.append("\n".join(texts))
        blocks.append("")
    return "\n".join(blocks).strip()
