"""压缩：把一堆文件打成一个 .zip，并如实汇报"到底省了多少"。

设计取舍：
- 只用 zipfile（标准库），不引入外部二进制，三平台行为一致；
- 压缩后重新读一遍归档，拿到真实的压缩后大小，而不是估算；
- 对 .bmp/.wav/.tiff 这类"本来就很密"的格式，收益低于阈值时主动提醒，
  避免用户以为工具坏了。
"""
from __future__ import annotations

import io
import os
import time
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

from ..errors import NothingToDo, ZipKitError
from .formats import HARD_TO_COMPRESS, describe, is_packable, suffix_of
from .safety import human

# 三档压缩级别，对应界面上的一次点击
LEVELS = {"fast": 1, "balanced": 6, "max": 9}
DEFAULT_LEVEL = "balanced"

# 收益低于这个比例（且属于"本就密集"的格式）就提醒用户
_WEAK_GAIN = 0.15


@dataclass
class EntryReport:
    """单个文件的压缩结果。"""

    name: str
    size: int
    compressed: int

    @property
    def savings(self) -> float:
        """节省比例 0~1。压缩后反而变大时为负数。"""
        if self.size <= 0:
            return 0.0
        return 1.0 - self.compressed / self.size

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "size": self.size,
            "compressed": self.compressed,
            "savings": round(self.savings, 4),
        }


@dataclass
class PackReport:
    """一次压缩的整体结果。"""

    out_path: Path
    entries: List[EntryReport] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    elapsed: float = 0.0

    @property
    def total_in(self) -> int:
        return sum(e.size for e in self.entries)

    @property
    def total_out(self) -> int:
        return sum(e.compressed for e in self.entries)

    @property
    def savings(self) -> float:
        if self.total_in <= 0:
            return 0.0
        return 1.0 - self.total_out / self.total_in

    def summary(self) -> str:
        return (
            f"{len(self.entries)} 个文件，"
            f"{human(self.total_in)} → {human(self.out_path.stat().st_size)}，"
            f"节省 {self.savings * 100:.1f}%"
        )

    def to_dict(self) -> dict:
        return {
            "out_path": str(self.out_path),
            "entries": [e.to_dict() for e in self.entries],
            "warnings": self.warnings,
            "elapsed": round(self.elapsed, 3),
            "total_in": self.total_in,
            "total_out": self.out_path.stat().st_size if self.out_path.exists() else self.total_out,
            "savings": round(self.savings, 4),
        }


def _resolve_level(level: str) -> int:
    key = (level or DEFAULT_LEVEL).lower()
    if key not in LEVELS:
        raise ZipKitError(
            f"不认识的压缩级别：{level}",
            "可选：fast（最快）、balanced（默认）、max（最小）",
        )
    return LEVELS[key]


def _unique_path(path: Path) -> Path:
    """目标已存在时加序号，绝不静默覆盖用户的文件。"""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(1, 1000):
        candidate = path.with_name(f"{stem} ({i}){suffix}")
        if not candidate.exists():
            return candidate
    raise ZipKitError(f"同名文件太多，无法生成新文件名：{path}")


def collect_inputs(inputs: Sequence[Path | str]) -> List[Tuple[Path, str]]:
    """把输入展开成 (绝对路径, 归档内名字) 列表。

    规则：
    - 单文件：用文件名作为归档内名字（不保留上级目录，避免泄漏本机路径）；
    - 目录：递归收集，保留目录内相对结构；
    - 同一个文件只打包一次（去重）。
    """
    pairs: List[Tuple[Path, str]] = []
    seen: set[str] = set()

    def add(file_path: Path, arcname: str) -> None:
        key = str(file_path.resolve())
        if key in seen:
            return
        seen.add(key)
        pairs.append((file_path, arcname))

    for raw in inputs:
        p = Path(raw).expanduser()
        if not p.exists():
            raise ZipKitError(
                f"找不到这个文件或目录：{p}",
                "检查路径是否拼错；路径里有空格时要用引号包起来",
            )
        if p.is_dir():
            root = p.resolve()
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames.sort()
                for filename in sorted(filenames):
                    full = Path(dirpath) / filename
                    rel = full.relative_to(root)
                    add(full, f"{p.name}/{rel.as_posix()}")
        else:
            add(p.resolve(), p.name)

    if not pairs:
        raise NothingToDo("没有找到可压缩的文件", "确认目录不是空的")
    return pairs


def pack(
    inputs: Sequence[Path | str],
    out_path: Path | str | None = None,
    level: str = DEFAULT_LEVEL,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> PackReport:
    """把 inputs 压缩成一个 zip，返回报告。

    Args:
        inputs: 文件或目录列表。
        out_path: 输出 zip；为空则生成 `zipkit-YYYYMMDD-HHMMSS.zip`。
        level: fast / balanced / max。
        progress: 可选回调 (当前序号, 总数, 当前文件名)。
    """
    started = time.time()
    compresslevel = _resolve_level(level)
    pairs = collect_inputs(inputs)

    if out_path is None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out_path = Path.cwd() / f"zipkit-{stamp}.zip"
    out_path = Path(out_path).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path = _unique_path(out_path)

    report = PackReport(out_path=out_path)
    total = len(pairs)

    try:
        with zipfile.ZipFile(
            out_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=compresslevel
        ) as zf:
            for index, (file_path, arcname) in enumerate(pairs, start=1):
                if progress:
                    progress(index, total, arcname)
                # ZIP 时间戳下限是 1980 年，过旧的文件会被写成 1980，属正常现象
                zf.write(file_path, arcname=arcname)
    except OSError as exc:
        raise ZipKitError(
            f"写入失败：{exc}",
            "检查目标目录是否有写权限，以及磁盘空间是否足够",
        ) from exc

    # 回读真实压缩后大小
    with zipfile.ZipFile(out_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            report.entries.append(
                EntryReport(name=info.filename, size=info.file_size, compressed=info.compress_size)
            )

    _collect_warnings(report, pairs)
    report.elapsed = time.time() - started
    return report


def entry_warnings(entries: Sequence[EntryReport]) -> List[str]:
    """根据压缩结果生成提示语（网页版和命令行共用）。"""
    warnings: List[str] = []

    weak = [
        e for e in entries
        if suffix_of(e.name) in HARD_TO_COMPRESS and e.size > 0 and e.savings < _WEAK_GAIN
    ]
    if weak:
        names = "、".join(e.name for e in weak[:5])
        more = f" 等 {len(weak)} 个文件" if len(weak) > 5 else ""
        warnings.append(
            f"{names}{more} 几乎压不动（节省不足 15%）。"
            "BMP/WAV/TIFF 属于高密度二进制，ZIP 对它们本来就没什么办法；"
            "想真正变小，BMP→PNG、WAV→FLAC、TIFF→PNG 才是正解。"
        )

    if entries and any(e.size == 0 for e in entries):
        warnings.append("有文件是空的（0 字节），压缩包里会保留空文件。")
    return warnings


def _collect_warnings(report: PackReport, pairs: Sequence[Tuple[Path, str]]) -> None:
    """在结果里追加"压不动"和"类型不推荐"的提示。"""
    report.warnings.extend(entry_warnings(report.entries))

    unusual = [p for p, _ in pairs if not is_packable(p)]
    if unusual:
        names = "、".join(p.name for p in unusual[:5])
        more = f" 等 {len(unusual)} 个" if len(unusual) > 5 else ""
        report.warnings.append(
            f"{names}{more} 不在推荐清单（txt/log/csv/json/bmp/wav/tiff）里，仍然打包了，"
            "但如果你是拿它们来验证功能，建议先用清单内的类型。"
        )


def pack_memory(
    files: Sequence[tuple], level: str = DEFAULT_LEVEL
) -> tuple:
    """把"文件名 + 字节内容"直接压进内存里的 zip，供网页版使用。

    网页版拿不到本机路径（浏览器安全限制），只能把内容传上来，
    所以这里不改临时文件、直接在 BytesIO 里完成压缩。

    Returns:
        (zip 字节, EntryReport 列表)
    """
    compresslevel = _resolve_level(level)
    buf = io.BytesIO()

    with zipfile.ZipFile(
        buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=compresslevel
    ) as zf:
        for name, data in files:
            info = zipfile.ZipInfo(filename=name, date_time=time.localtime()[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=compresslevel)

    payload = buf.getvalue()
    entries: List[EntryReport] = []
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            entries.append(
                EntryReport(name=info.filename, size=info.file_size, compressed=info.compress_size)
            )
    return payload, entries


def quick_ratio(path: Path | str, sample_bytes: int = 1024 * 1024) -> float:
    """快速估算压缩率：只压文件的头 1 MB，几毫秒出结果。

    用途：用户拖进来一个 4 GB 的 wav 之前，先告诉他"大概只能省 20%"。
    返回 0~1 的节省比例；文件为空或不可读时返回 0。
    """
    p = Path(path)
    try:
        with open(p, "rb") as f:
            chunk = f.read(sample_bytes)
    except OSError:
        return 0.0
    if not chunk:
        return 0.0
    compressed = len(zlib.compress(chunk, 6))
    return max(0.0, 1.0 - compressed / len(chunk))


def check_files(paths: Sequence[Path | str]) -> List[dict]:
    """体检：识别类型 + 预估压缩收益，供 `zipkit check` 使用。"""
    rows: List[dict] = []
    for raw in paths:
        p = Path(raw).expanduser()
        if not p.exists():
            rows.append({"path": str(p), "error": "文件不存在"})
            continue
        if p.is_dir():
            rows.append({"path": str(p), "kind": "目录", "note": "会递归打包"})
            continue
        rows.append(
            {
                "path": str(p),
                "kind": suffix_of(p) or "无扩展名",
                "size": p.stat().st_size,
                "note": describe(p),
                "estimated_savings": round(quick_ratio(p), 3),
            }
        )
    return rows
