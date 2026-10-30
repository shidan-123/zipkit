#!/usr/bin/env python3
"""生成演示用的样例文件（8 类可压缩 + 3 类 Office 文档）。

用法：
    python scripts/make_demo.py            # 生成到 ./demo/
    python scripts/make_demo.py 某目录      # 生成到指定目录

这些文件都是"真文件"，不是空壳：BMP 是真位图、WAV 是真音频、
docx/xlsx/pptx 由官方库生成，拿去压缩/解压/提取都能验证真实效果。
"""
from __future__ import annotations

import json
import math
import struct
import sys
import wave
from pathlib import Path


def make_text(folder: Path) -> None:
    (folder / "会议纪要.txt").write_text(
        "项目周会纪要 2026-10-30\n" + "=" * 40 + "\n"
        + "".join(f"{i:03d}. 待办事项：确认第 {i} 批文件的压缩结果\n" for i in range(1, 120)),
        encoding="utf-8",
    )
    (folder / "app-2026-10-30.log").write_text(
        "".join(
            f"2026-10-30 10:{i // 60 % 60:02d}:{i % 60:02d} INFO  "
            f"handler=ItemHandler method=GET path=/api/v1/items/{i % 40} "
            f"status=200 elapsed={i % 30}ms trace=abc{i % 7}\n"
            for i in range(4000)
        ),
        encoding="utf-8",
    )
    rows = ["学号,姓名,语文,数学,英语,总分"]
    for i in range(1, 401):
        scores = [60 + (i * k) % 40 for k in (1, 2, 3)]
        rows.append(f"2026{i:03d},学生{i % 50},{scores[0]},{scores[1]},{scores[2]},{sum(scores)}")
    (folder / "成绩表.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (folder / "config.json").write_text(
        json.dumps(
            {
                "app": "zipkit-demo",
                "version": 1,
                "features": [{"id": i, "enabled": i % 3 != 0} for i in range(200)],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def make_bmp(path: Path, width: int = 320, height: int = 200) -> None:
    """手写 24 位未压缩 BMP（不依赖 Pillow）。"""
    row_size = (width * 3 + 3) // 4 * 4
    pixels = bytearray()
    for y in range(height):
        row = bytearray()
        for x in range(width):
            row += bytes(((x * 255) // width, (y * 255) // height, (x * y) % 256))
        row += b"\x00" * (row_size - len(row))
        pixels += row
    size = 14 + 40 + len(pixels)
    header = b"BM" + struct.pack("<IHHI", size, 0, 0, 54)
    dib = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(pixels), 2835, 2835, 0, 0)
    path.write_bytes(header + dib + bytes(pixels))


def make_wav(path: Path, seconds: float = 2.0, rate: int = 16000) -> None:
    frames = bytearray()
    for i in range(int(seconds * rate)):
        value = int(9000 * math.sin(2 * math.pi * 440 * i / rate))
        frames += struct.pack("<h", value)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(frames))


def make_tiff(path: Path) -> bool:
    try:
        from PIL import Image
    except Exception:
        print("  （跳过 TIFF：没装 Pillow，执行 pip install pillow 可生成）")
        return False
    img = Image.new("RGB", (200, 150))
    px = img.load()
    for y in range(150):
        for x in range(200):
            px[x, y] = ((x * 255) // 200, (y * 255) // 150, (x + y) % 256)
    img.save(path, format="TIFF")
    return True


def make_office(folder: Path) -> None:
    try:
        import docx

        document = docx.Document()
        document.add_heading("ZipKit 演示文档", level=1)
        document.add_paragraph("这是一份用于演示【读取文档】功能的 Word 文件。")
        document.add_paragraph("你可以用 zipkit text 演示文档.docx 把文字抽出来。")
        document.save(str(folder / "演示文档.docx"))
    except Exception:
        print("  （跳过 docx：pip install python-docx 可生成）")

    try:
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "成绩表"
        ws.append(["姓名", "分数", "评价"])
        ws.append(["张三", 95, "优秀"])
        ws.append(["李四", 78, "良好"])
        wb.save(str(folder / "演示表格.xlsx"))
    except Exception:
        print("  （跳过 xlsx：pip install openpyxl 可生成）")

    try:
        import pptx

        prs = pptx.Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = "ZipKit 演示幻灯片"
        slide.placeholders[1].text = "这是第一页的正文内容。"
        slide2 = prs.slides.add_slide(prs.slide_layouts[1])
        slide2.shapes.title.text = "第二页"
        slide2.placeholders[1].text = "压缩包里的 pptx 也能解开看结构。"
        prs.save(str(folder / "演示幻灯片.pptx"))
    except Exception:
        print("  （跳过 pptx：pip install python-pptx 可生成）")


def main() -> int:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "demo").resolve()
    target.mkdir(parents=True, exist_ok=True)

    make_text(target)
    make_bmp(target / "示意图.bmp")
    make_wav(target / "提示音.wav")
    make_tiff(target / "扫描件.tiff")
    make_office(target)

    print(f"\n✅ 样例已生成到：{target}\n")
    for item in sorted(target.iterdir()):
        print(f"   {item.name:<24} {item.stat().st_size / 1024:>9.1f} KB")
    print("\n下一步试一下：\n   python -m zipkit check demo/*\n   python -m zipkit pack demo -o demo.zip\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
