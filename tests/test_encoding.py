"""压缩包成员名编码修复的测试。

真实场景：Windows 资源管理器用 GBK 打包中文名时**不写 UTF-8 标记位**，
解压库只能按 cp437 解码，于是 `小黑课堂.exe` 变成 `╨í║┌┐╬....exe`。
"""
from __future__ import annotations

import pytest

from zipkit.core.encoding import UTF8_FLAG, repair_zip_name


def _mangle(text: str, encoding: str = "gbk") -> str:
    """模拟"GBK 字节被当成 cp437 解码"的乱码结果。"""
    return text.encode(encoding).decode("cp437")


def test_gbk_name_is_repaired() -> None:
    mangled = _mangle("小黑课堂计算机二级题库.exe")
    assert mangled != "小黑课堂计算机二级题库.exe"      # 确认真的乱码了
    assert repair_zip_name(mangled, 0) == "小黑课堂计算机二级题库.exe"


def test_ascii_name_is_untouched() -> None:
    assert repair_zip_name("notes.txt", 0) == "notes.txt"
    assert repair_zip_name("dir/sub/file.log", 0) == "dir/sub/file.log"


def test_utf8_flagged_name_is_trusted() -> None:
    """打包时已声明 UTF-8 的，不做任何猜测。"""
    name = "中文名字.txt"
    assert repair_zip_name(name, UTF8_FLAG) == name
    # 即使内容看起来像乱码，只要带了标记就不动它
    mangled = _mangle("测试.txt")
    assert repair_zip_name(mangled, UTF8_FLAG) == mangled


def test_unrepairable_name_falls_back() -> None:
    """无法还原的字符串原样返回，绝不抛异常。"""
    weird = "\u4e2d\u6587"  # 正常中文，不是 cp437 能编码的
    assert repair_zip_name(weird, 0) == weird


@pytest.mark.parametrize("text", ["报告.txt", "数据 2026.csv", "子目录/文件.log"])
def test_various_gbk_names(text: str) -> None:
    assert repair_zip_name(_mangle(text), 0) == text
