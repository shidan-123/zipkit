#!/usr/bin/env python3
"""生成 macOS 应用图标（AppIcon.icns）。

用法：python3 scripts/make_icon.py
依赖：Pillow（仅生成图标时需要，运行 ZipKit 不需要）
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "ZipKit.app"
ICONSET = APP / "Contents" / "Resources" / "AppIcon.iconset"
ICNS = APP / "Contents" / "Resources" / "AppIcon.icns"

# macOS iconset 需要的尺寸（名字必须完全一致）
SIZES = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}


def draw(size: int = 1024):
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    pad = size // 12
    radius = size // 5
    d.rounded_rectangle(
        [pad, pad, size - pad, size - pad], radius=radius, fill=(37, 99, 235, 255)
    )

    # 内层浅色框，像一张"档案卡片"
    inset = size // 5
    d.rounded_rectangle(
        [inset, inset, size - inset, size - inset],
        radius=radius // 2,
        fill=(255, 255, 255, 235),
    )

    # 中间的拉链：竖线 + 齿
    cx = size // 2
    top, bottom = int(size * 0.30), int(size * 0.62)
    width = max(3, size // 64)
    d.line([cx, top, cx, bottom], fill=(37, 99, 235, 255), width=width * 2)
    tooth = size // 22
    y = top
    side = 1
    while y < bottom:
        d.rectangle([cx - tooth, y, cx - width, y + tooth // 2], fill=(37, 99, 235, 255))
        d.rectangle([cx + width, y + tooth // 2, cx + tooth, y + tooth], fill=(37, 99, 235, 255))
        y += tooth
        side *= -1

    # 底部 ZIP 字样
    try:
        from PIL import ImageFont

        font = None
        for path in (
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ):
            try:
                font = ImageFont.truetype(path, size // 7)
                break
            except OSError:
                continue
        text = "ZIP"
        if font is not None:
            box = d.textbbox((0, 0), text, font=font)
            w, h = box[2] - box[0], box[3] - box[1]
            d.text(((size - w) / 2 - box[0], size * 0.70), text, font=font, fill=(37, 99, 235, 255))
    except Exception:
        pass

    return img


def main() -> int:
    try:
        from PIL import Image
    except Exception:
        print("需要 Pillow：pip install pillow", file=sys.stderr)
        return 1

    if shutil.which("iconutil") is None:
        print("找不到 iconutil（仅 macOS 需要）", file=sys.stderr)
        return 1

    if ICONSET.exists():
        shutil.rmtree(ICONSET)
    ICONSET.mkdir(parents=True)

    base = draw(1024)
    with tempfile.TemporaryDirectory() as tmp:
        master = Path(tmp) / "master.png"
        base.save(master)
        for name, px in SIZES.items():
            out = ICONSET / name
            subprocess.run(
                ["sips", "-z", str(px), str(px), str(master), "--out", str(out)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

    subprocess.run(["iconutil", "-c", "icns", str(ICONSET), "-o", str(ICNS)], check=True)
    shutil.rmtree(ICONSET)
    print(f"✅ 图标已生成：{ICNS}（{ICNS.stat().st_size / 1024:.1f} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
