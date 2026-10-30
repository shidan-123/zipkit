"""压缩包成员名的编码修复。

ZIP 规范里有个"UTF-8 标记位"（通用位 11）。Windows 资源管理器用 GBK 打包中文名时，
**不加这个标记**，于是解压库只能按 cp437 解码，中文就变成 `╨í║┌┐╬` 这种乱码。

这里做的是"反向还原"：把 cp437 解出来的字符串重新编回原始字节，
再用 GBK / GB18030 / Big5 试一遍。还原不出来就原样返回，绝不猜坏。
"""
from __future__ import annotations

UTF8_FLAG = 0x800

# 依次尝试：GB18030 是 GBK 的超集，优先它更稳；Big5 兜底港澳台老包
_CANDIDATE_ENCODINGS = ("gb18030", "gbk", "big5")


def repair_zip_name(name: str, flag_bits: int) -> str:
    """若成员名看起来是 GBK 被误读成 cp437，则还原成正确的中文。

    Args:
        name: 解压库解出来的名字（通常是 cp437 解码结果）。
        flag_bits: ZIP 成员的通用标志位。

    Returns:
        能还原就返回还原后的名字，否则原样返回。

    Examples:
        >>> repair_zip_name("notes.txt", 0)
        'notes.txt'
    """
    if flag_bits & UTF8_FLAG:
        return name  # 打包时已声明 UTF-8，相信它
    try:
        raw = name.encode("cp437")
    except UnicodeEncodeError:
        return name  # 不是纯 cp437 能表示的字符，说明已被正确解码

    for encoding in _CANDIDATE_ENCODINGS:
        try:
            fixed = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        # 解码成功但出现控制字符，说明猜错了编码，别用
        if not fixed or any(ord(ch) < 32 for ch in fixed):
            continue
        if fixed == name:
            return name  # 纯 ASCII，无需改动
        return fixed

    return name
