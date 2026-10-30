"""格式知识库。

这里集中回答三个问题：
1. 这个扩展名我们能不能"压缩"？
2. 压缩它到底能省多少空间（很多文件其实是压不动的）？
3. 这个扩展名到底是普通归档，还是 ZIP 套壳的 Office 文档？
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------- 可压缩的文件
# 用户明确要求的 8 类。注意：能压缩 ≠ 压得动，见 FORMAT_NOTES。
PACKABLE_EXTS = {
    ".txt", ".log", ".csv", ".json",      # 文本类：压缩率很高
    ".bmp", ".wav", ".tiff", ".tif",      # 媒体类：ZIP 收益有限
}

# 每个格式的"人话说明"，用于界面提示和 README。
FORMAT_NOTES = {
    ".txt": "纯文本，通常能压掉 60%~90%",
    ".log": "日志文本，重复度极高，通常能压掉 80%~95%",
    ".csv": "表格文本，重复度高，通常能压掉 70%~90%",
    ".json": "结构化文本，通常能压掉 60%~85%",
    ".bmp": "未压缩位图，ZIP 大概能省 30%~70%；但换成 PNG 会小得多",
    ".wav": "未压缩音频（PCM），ZIP 只能省 10%~40%；换成 FLAC 能省一半左右",
    ".tiff": "TIFF 常常本身已是 LZW 压缩，ZIP 可能只省 0%~30%",
    ".tif": "同 .tiff",
}

# 这些格式属于"本来就压过了"，用 ZIP 再压收益很低，需要给出提示。
HARD_TO_COMPRESS = {".bmp", ".wav", ".tiff", ".tif"}

# 已经具备压缩能力、一眼看起来"没啥可压"的格式（提示用户别指望）
ALREADY_COMPRESSED = {
    ".zip", ".7z", ".gz", ".tgz", ".bz2", ".xz", ".rar", ".zst",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp3", ".mp4", ".aac", ".avi", ".mkv",
}

# ---------------------------------------------------------------- 可解压的归档
ARCHIVE_EXTS = {".zip", ".7z", ".gz", ".tgz", ".tar", ".tar.gz"}

# ZIP 套壳的办公文档（OOXML）。它们本质就是 ZIP，但"解开"后是 XML，不是给人看的。
OOXML_EXTS = {".docx", ".xlsx", ".pptx"}

# 双扩展名（.tar.gz）需要特殊处理，suffix 只认最后一个点。
_COMPOUND_SUFFIXES = (".tar.gz", ".tar.bz2", ".tar.xz")


def suffix_of(path: Path | str) -> str:
    """返回小写扩展名，能正确处理 .tar.gz 这类双扩展名。"""
    name = Path(path).name.lower()
    for compound in _COMPOUND_SUFFIXES:
        if name.endswith(compound):
            return compound
    return Path(name).suffix


def is_packable(path: Path | str) -> bool:
    return suffix_of(path) in PACKABLE_EXTS


def is_archive(path: Path | str) -> bool:
    return suffix_of(path) in ARCHIVE_EXTS or is_ooxml(path)


def is_ooxml(path: Path | str) -> bool:
    return suffix_of(path) in OOXML_EXTS


def describe(path: Path | str) -> str:
    """给一个文件类型的人话解释，用于界面上的提示条。"""
    ext = suffix_of(path)
    if ext in FORMAT_NOTES:
        return FORMAT_NOTES[ext]
    if ext in ALREADY_COMPRESSED:
        return "这类文件通常已经压缩过，再压缩几乎不会变小"
    if ext in OOXML_EXTS:
        return "Office 文档本质是 ZIP 容器；解开得到的是 XML，不是给人读的内容"
    if ext in ARCHIVE_EXTS:
        return "这已经是压缩包，解开它才有意义"
    return "未知类型，会按普通文件打包"
