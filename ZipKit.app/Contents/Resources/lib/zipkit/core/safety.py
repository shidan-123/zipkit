"""安全防护：路径穿越、符号链接、覆盖、解压炸弹。

这些检查看起来"啰嗦"，但它们是这个工具能不能公开给别人用的分界线。
一个恶意 ZIP 只要有一个 `../../.ssh/authorized_keys` 成员，
就能在用户不知情时覆盖掉关键文件——所以每一层都必须拦住。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from ..errors import LimitsExceeded, UnsafeArchiveError

# Windows 盘符，例如 C:\ 或 C:/，以及统一命名路径 \\?\C:\
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_UNC_PREFIXES = ("\\\\", "//")

# Windows 设备名：这些名字即使在子目录里也可能触发异常行为
_WIN_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


@dataclass(frozen=True)
class Limits:
    """解压时的安全上限（默认值面向普通用户，够用且安全）。"""

    max_files: int = 20_000            # 最多多少个成员
    max_total: int = 2 * 1024 ** 3     # 解压后总量最多 2 GB
    max_single: int = 1 * 1024 ** 3    # 单个文件最多 1 GB
    max_ratio: int = 200               # 压缩比上限，超过视为炸弹
    ratio_floor_bytes: int = 2 * 1024 ** 2  # 小文件不参与压缩比判断（避免误杀）

    def check_file_count(self, count: int) -> None:
        if count > self.max_files:
            raise LimitsExceeded(
                f"压缩包里有 {count} 个文件，超过安全上限 {self.max_files} 个",
                "如果你确认来源可信，可以在命令行加 --max-files 调高上限",
            )

    def check_declared_size(self, total: int) -> None:
        if total > self.max_total:
            raise LimitsExceeded(
                f"解压后总量约 {human(total)}，超过安全上限 {human(self.max_total)}",
                "确认来源可信后可加 --max-total 调高上限",
            )

    def check_single(self, size: int) -> None:
        if size > self.max_single:
            raise LimitsExceeded(
                f"单个文件 {human(size)}，超过安全上限 {human(self.max_single)}",
                "确认来源可信后可加 --max-single 调高上限",
            )

    def check_ratio(self, name: str, uncompressed: int, compressed: int) -> None:
        if uncompressed < self.ratio_floor_bytes:
            return
        ratio = uncompressed / max(compressed, 1)
        if ratio > self.max_ratio:
            raise LimitsExceeded(
                f"{name} 的压缩比高达 {ratio:.0f}:1，疑似压缩炸弹",
                "如果这确实是一个正常的高压缩文件（例如全零日志），可加 --max-ratio 调高上限",
            )


DEFAULT_LIMITS = Limits()


def human(n: float) -> str:
    """把字节数变成人话：1536 -> 1.5 KB。"""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(n)} B"
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def normalize_member(name: str) -> str:
    """把压缩包里的成员名统一成 posix 风格，便于检查。"""
    return name.replace("\\", "/")


def validate_member(name: str) -> str:
    """检查一个成员名是否安全；安全则返回规范化后的相对路径。

    拒绝：绝对路径、盘符、UNC、`..`、空名、控制字符、Windows 设备名。
    """
    clean = normalize_member(name)

    if not clean or clean in (".", "./"):
        raise UnsafeArchiveError("压缩包里有空文件名", "这个包可能已损坏，建议重新下载")

    if clean.startswith(_UNC_PREFIXES) or clean.startswith("/"):
        raise UnsafeArchiveError(
            f"拒绝绝对路径成员：{name}",
            "正常压缩包只应包含相对路径。这个包可能是恶意构造的。",
        )

    if _DRIVE_RE.match(clean):
        raise UnsafeArchiveError(
            f"拒绝带盘符的成员：{name}",
            "正常压缩包不会出现 C:\\ 这种路径。这个包可能是恶意构造的。",
        )

    if any(ord(ch) < 32 for ch in clean):
        raise UnsafeArchiveError(
            f"成员名包含控制字符：{name!r}",
            "可能是伪造的扩展名，建议放弃解压这个包",
        )

    parts: list[str] = []
    for part in clean.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise UnsafeArchiveError(
                f"拒绝跳目录的成员：{name}（含 ..）",
                "这是典型的 ZIP 路径穿越攻击，已拦截。如果你信任这个包，可手工解压并检查。",
            )
        if part.split(".")[0].lower() in _WIN_RESERVED:
            raise UnsafeArchiveError(
                f"成员名使用了 Windows 保留名：{name}",
                "这类文件在 Windows 上会引发异常，已跳过。",
            )
        parts.append(part)

    if not parts:
        raise UnsafeArchiveError(f"成员名无效：{name}", "这个包可能已损坏")

    return "/".join(parts)


def safe_join(base: Path, member: str) -> Path:
    """把成员名拼到目标目录下，并确保结果一定在目标目录内部。"""
    checked = validate_member(member)
    base_abs = base.resolve()
    target = base_abs.joinpath(*checked.split("/"))

    # 防御纵深：即使前面漏了，这里再验一次真实路径
    resolved = target.resolve(strict=False)
    try:
        if os.path.commonpath([str(base_abs), str(resolved)]) != str(base_abs):
            raise UnsafeArchiveError(
                f"成员会写到目标目录之外：{member}",
                "已拦截。请谨慎处理这个压缩包。",
            )
    except ValueError:
        # 不同盘符时 commonpath 会抛 ValueError，同样视为不安全
        raise UnsafeArchiveError(
            f"成员会写到目标目录之外：{member}", "已拦截。"
        ) from None

    return target
