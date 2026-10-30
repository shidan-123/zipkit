"""测试用的样例文件生成器。

原则：每一种用户点名的格式，都必须有一个"真文件"能被压缩/解压一遍，
而不是拿假数据糊弄——真文件才能暴露编码、时间戳、二进制对齐的问题。
"""
from __future__ import annotations

import json
import math
import struct
import wave
from pathlib import Path

import pytest


# ------------------------------------------------------------------ 文本类
def _write_text_samples(folder: Path) -> None:
    (folder / "notes.txt").write_text(
        "ZipKit 测试文本\n" * 200 + "最后一行\n", encoding="utf-8"
    )
    (folder / "app.log").write_text(
        "".join(
            f"2026-10-30 10:00:{i % 60:02d} INFO  request id={i % 50} path=/api/v1/items "
            f"status=200 elapsed=12ms\n"
            for i in range(3000)
        ),
        encoding="utf-8",
    )
    rows = ["id,name,score,city"]
    for i in range(2000):
        rows.append(f"{i},用户{i % 300},{i % 100},城市{i % 20}")
    (folder / "data.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (folder / "config.json").write_text(
        json.dumps(
            {"version": 3, "items": [{"id": i, "tags": ["a", "b", "c"]} for i in range(400)]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


# ------------------------------------------------------------------ 媒体类
def _write_bmp(path: Path, width: int = 96, height: int = 64) -> None:
    """手写 24 位未压缩 BMP，不依赖 Pillow（保证任何环境都能测）。"""
    row_size = (width * 3 + 3) // 4 * 4
    pixels = bytearray()
    for y in range(height):
        row = bytearray()
        for x in range(width):
            row += bytes(((x * 3) % 256, (y * 5) % 256, (x + y) % 256))
        row += b"\x00" * (row_size - len(row))
        pixels += row

    file_size = 14 + 40 + len(pixels)
    header = b"BM" + struct.pack("<IHHI", file_size, 0, 0, 54)
    dib = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(pixels), 2835, 2835, 0, 0)
    path.write_bytes(header + dib + bytes(pixels))


def _write_wav(path: Path, seconds: float = 0.5, rate: int = 8000) -> None:
    frames = bytearray()
    total = int(seconds * rate)
    for i in range(total):
        value = int(12000 * math.sin(2 * math.pi * 440 * i / rate))
        frames += struct.pack("<h", value)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(frames))


def _write_tiff(path: Path) -> bool:
    """有 Pillow 就用 Pillow 写真 TIFF；没有就跳过（返回 False）。"""
    try:
        from PIL import Image
    except Exception:
        return False
    img = Image.new("RGB", (64, 48))
    pixels = img.load()
    for y in range(48):
        for x in range(64):
            pixels[x, y] = ((x * 4) % 256, (y * 5) % 256, (x * y) % 256)
    img.save(path, format="TIFF")
    return True


# ------------------------------------------------------------------ 夹具
@pytest.fixture
def sample_dir(tmp_path: Path) -> Path:
    """8 类"压缩目标"文件（TIFF 需要 Pillow）。"""
    folder = tmp_path / "samples"
    folder.mkdir()
    _write_text_samples(folder)
    _write_bmp(folder / "picture.bmp")
    _write_wav(folder / "tone.wav")
    _write_tiff(folder / "scan.tiff")
    return folder


@pytest.fixture
def text_only_dir(tmp_path: Path) -> Path:
    """只要文本样本时用，跑得更快。"""
    folder = tmp_path / "texts"
    folder.mkdir()
    _write_text_samples(folder)
    return folder


@pytest.fixture
def office_dir(tmp_path: Path) -> Path:
    """真的 docx / xlsx / pptx（用官方库生成，和用户手里的一致）。"""
    docx = pytest.importorskip("docx")
    openpyxl = pytest.importorskip("openpyxl")
    pptx = pytest.importorskip("pptx")

    folder = tmp_path / "office"
    folder.mkdir()

    document = docx.Document()
    document.add_heading("ZipKit 测试文档", level=1)
    document.add_paragraph("第一段：这是一段用于验证提取效果的正文。")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "姓名"
    table.cell(0, 1).text = "分数"
    table.cell(1, 0).text = "张三"
    table.cell(1, 1).text = "95"
    document.save(str(folder / "report.docx"))

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "成绩表"
    sheet.append(["姓名", "分数", "备注"])
    sheet.append(["张三", 95, "优秀"])
    sheet.append(["李四", 78, "良好"])
    workbook.save(str(folder / "grades.xlsx"))

    presentation = pptx.Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "第一页标题"
    slide.placeholders[1].text = "第一页正文内容"
    slide2 = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide2.shapes.title.text = "第二页标题"
    slide2.placeholders[1].text = "第二页正文内容"
    presentation.save(str(folder / "deck.pptx"))

    return folder
