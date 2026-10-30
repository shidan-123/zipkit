"""统一的异常定义。

每个异常都带 `message`（发生了什么）和 `hint`（该怎么办），
这样命令行和网页界面都能直接把两句话展示给用户，不需要再翻译。
"""
from __future__ import annotations


class ZipKitError(Exception):
    """ZipKit 所有错误的基类。"""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def to_dict(self) -> dict:
        return {"error": self.message, "hint": self.hint}


class UnsafeArchiveError(ZipKitError):
    """归档里有会逃出目标目录的路径（zip slip / 路径穿越）。"""


class ArchiveFormatError(ZipKitError):
    """文件不是它扩展名声称的格式，或文件已损坏。"""


class LimitsExceeded(ZipKitError):
    """超过安全上限（解压总量、单个文件、压缩比、文件数量）。"""


class MissingDependency(ZipKitError):
    """需要安装可选依赖才能处理这种格式。"""


class NothingToDo(ZipKitError):
    """没有可处理的内容。"""
