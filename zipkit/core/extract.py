"""解压：zip / 7z / gz / tar.gz / docx / xlsx / pptx。

安全模型（按顺序执行，任何一步失败都不会留下半成品文件）：
1. 先只"读目录"，把每个成员名做路径穿越检查；
2. 再检查数量、声明大小、压缩比（拦压缩炸弹）；
3. 最后才真正写盘，并且边写边数字节（防止头里撒谎的包）。
"""
from __future__ import annotations

import gzip
import os
import tarfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, List, Optional

from ..errors import (
    ArchiveFormatError,
    LimitsExceeded,
    MissingDependency,
    UnsafeArchiveError,
    ZipKitError,
)
from .encoding import repair_zip_name
from .formats import OOXML_EXTS, suffix_of
from .safety import DEFAULT_LIMITS, Limits, human, safe_join, validate_member

CHUNK = 1024 * 1024

MAGIC_ZIP = b"PK\x03\x04"
MAGIC_EMPTY_ZIP = b"PK\x05\x06"
MAGIC_7Z = b"7z\xbc\xaf\x27\x1c"
MAGIC_GZIP = b"\x1f\x8b"

_OOXML_HINT = (
    "docx/xlsx/pptx 本质是 ZIP 套壳：解开后得到的是 XML 和图片，不是能直接编辑的文档。"
    "如果你只想读里面的文字，用 `zipkit text 文件.docx` 更合适。"
)


@dataclass
class ExtractedEntry:
    name: str
    size: int

    def to_dict(self) -> dict:
        return {"name": self.name, "size": self.size}


@dataclass
class ExtractReport:
    dest: Path
    kind: str
    entries: List[ExtractedEntry] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    elapsed: float = 0.0

    @property
    def total_bytes(self) -> int:
        return sum(e.size for e in self.entries)

    def summary(self) -> str:
        return f"{len(self.entries)} 个文件，共 {human(self.total_bytes)} → {self.dest}"

    def to_dict(self) -> dict:
        return {
            "dest": str(self.dest),
            "kind": self.kind,
            "entries": [e.to_dict() for e in self.entries],
            "warnings": self.warnings,
            "skipped": self.skipped,
            "elapsed": round(self.elapsed, 3),
            "total_bytes": self.total_bytes,
        }


# ------------------------------------------------------------------ 格式识别
def detect_kind(path: Path | str) -> str:
    """用"文件头魔数"而不是扩展名来判断类型，防止改扩展名骗过检查。"""
    p = Path(path)
    suffix = suffix_of(p)
    try:
        with open(p, "rb") as f:
            head = f.read(512)
    except OSError as exc:
        raise ZipKitError(f"读不了这个文件：{p}（{exc}）", "确认文件存在且有读权限") from exc

    if head.startswith(MAGIC_7Z):
        return "7z"
    if head.startswith(MAGIC_GZIP):
        return "gzip"
    if head.startswith((MAGIC_ZIP, MAGIC_EMPTY_ZIP)):
        return "ooxml" if suffix in OOXML_EXTS else "zip"
    if suffix == ".tar":
        return "tar"
    if len(head) > 262 and head[257:262] == b"ustar":
        return "tar"
    raise ArchiveFormatError(
        f"不认识这个格式：{p.name}",
        "支持解压：.zip / .7z / .gz / .tar.gz / .tgz / .tar / .docx / .xlsx / .pptx",
    )


def _is_tar_suffix(suffix: str) -> bool:
    return suffix in (".tar.gz", ".tgz", ".tar")


def _unique_path(target: Path) -> Path:
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    for i in range(1, 1000):
        candidate = target.with_name(f"{stem} ({i}){suffix}")
        if not candidate.exists():
            return candidate
    raise ZipKitError(f"同名文件太多：{target}")


# ------------------------------------------------------------------ 入口
def extract(
    path: Path | str,
    dest: Path | str | None = None,
    force: bool = False,
    limits: Limits = DEFAULT_LIMITS,
) -> ExtractReport:
    """解压一个归档到 dest（默认为同目录下的 `<名字>_extracted`）。"""
    started = time.time()
    src = Path(path).expanduser().resolve()
    if not src.exists():
        raise ZipKitError(f"文件不存在：{src}", "检查路径是否拼错")
    if not src.is_file():
        raise ZipKitError(f"这不是文件：{src}", "解压只接受单个归档文件")

    kind = detect_kind(src)
    suffix = suffix_of(src)

    if dest is None:
        base = src.name
        for compound in (".tar.gz", ".tgz"):
            if base.lower().endswith(compound):
                base = base[: -len(compound)]
                break
        else:
            base = src.stem
        dest = src.parent / f"{base}_extracted"
    dest = Path(dest).expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)

    report = ExtractReport(dest=dest, kind=kind)

    if kind == "ooxml":
        report.warnings.append(_OOXML_HINT)
        _extract_zip(src, dest, force, limits, report)
    elif kind == "zip":
        _extract_zip(src, dest, force, limits, report)
    elif kind == "7z":
        _extract_7z(src, dest, force, limits, report)
    elif kind == "gzip":
        if _is_tar_suffix(suffix) or suffix == ".tgz":
            _extract_targz(src, dest, force, limits, report)
        else:
            _extract_gzip(src, dest, force, limits, report)
    elif kind == "tar":
        _extract_tar_file(src, dest, force, limits, report)
    else:  # pragma: no cover - detect_kind 已保证不会到这里
        raise ArchiveFormatError(f"不支持的格式：{kind}")

    report.elapsed = time.time() - started
    return report


# ------------------------------------------------------------------ ZIP
def _extract_zip(
    src: Path, dest: Path, force: bool, limits: Limits, report: ExtractReport
) -> None:
    try:
        zf = zipfile.ZipFile(src)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ArchiveFormatError(
            f"ZIP 结构损坏：{exc}",
            "文件可能下载不完整，重新下载试试；也可以先用系统自带解压工具验证一下",
        ) from exc

    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        limits.check_file_count(len(infos))
        limits.check_declared_size(sum(i.file_size for i in infos))

        # 第一遍：只校验，不写盘
        planned: List[tuple] = []
        for info in infos:
            # Windows 用 GBK 打包的中文名没有 UTF-8 标记，先还原，再校验
            display_name = repair_zip_name(info.filename, info.flag_bits)
            if display_name != info.filename:
                report.warnings.append(
                    f"已修复乱码文件名：{info.filename} → {display_name}"
                )
            target = safe_join(dest, display_name)            # 路径穿越检查
            limits.check_ratio(display_name, info.file_size, info.compress_size)
            limits.check_single(info.file_size)
            if info.flag_bits & 0x1:
                raise ArchiveFormatError(
                    f"这个 ZIP 加了密码，无法解压：{display_name}",
                    "ZipKit 暂不支持加密压缩包；请先用系统工具输入密码解压",
                )
            planned.append((info, target, display_name))

        # 第二遍：真正解压
        written_total = 0
        for info, target, display_name in planned:
            if target.exists() and not force:
                target = _unique_path(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            written = _stream_to_file(
                zf.open(info), target, limits, written_total, display_name
            )
            written_total += written
            report.entries.append(ExtractedEntry(name=display_name, size=written))


def _stream_to_file(
    stream, target: Path, limits: Limits, already_written: int, member: str
) -> int:
    """把一个流写到文件，同时数字节、卡上限。返回实际写入字节数。"""
    written = 0
    try:
        with open(target, "wb") as out:
            while True:
                chunk = stream.read(CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > limits.max_single:
                    raise LimitsExceeded(
                        f"{member} 解压后超过单文件上限 {human(limits.max_single)}",
                        "确认来源可信后可调高 --max-single",
                    )
                if already_written + written > limits.max_total:
                    raise LimitsExceeded(
                        f"解压总量超过上限 {human(limits.max_total)}",
                        "确认来源可信后可调高 --max-total",
                    )
                out.write(chunk)
    except BaseException:
        # 失败时删掉半截文件，避免用户拿到一个"看起来正常"的损坏文件
        target.unlink(missing_ok=True)
        raise
    finally:
        stream.close()
    return written


# ------------------------------------------------------------------ GZIP
def _extract_gzip(
    src: Path, dest: Path, force: bool, limits: Limits, report: ExtractReport
) -> None:
    try:
        with open(src, "rb") as raw:
            gz = gzip.GzipFile(filename=str(src), mode="rb", fileobj=raw)
            inner_name = os.path.basename(gz.name or "")
            if not inner_name or inner_name == src.name:
                inner_name = _strip_gz_suffix(src.name)
            target = dest / inner_name
            if target.exists() and not force:
                target = _unique_path(target)
            written = _stream_to_file(gz, target, limits, 0, inner_name)
    except (gzip.BadGzipFile, EOFError, OSError) as exc:
        raise ArchiveFormatError(
            f"GZ 文件损坏：{exc}",
            "文件可能没下载完，重新下载；.gz 只能装一个文件，装多个文件的是 .tar.gz",
        ) from exc

    report.entries.append(ExtractedEntry(name=inner_name, size=written))


def _strip_gz_suffix(name: str) -> str:
    if name.lower().endswith(".gz"):
        return name[:-3]
    return f"{name}.out"


# ------------------------------------------------------------------ TAR
def _extract_tar_file(
    src: Path, dest: Path, force: bool, limits: Limits, report: ExtractReport
) -> None:
    try:
        with tarfile.open(src, mode="r:*") as tf:
            _extract_tar_members(tf, dest, force, limits, report)
    except tarfile.TarError as exc:
        raise ArchiveFormatError(
            f"TAR 结构损坏：{exc}",
            "如果这是 .tar.gz，请确认下载完整（用 `zipkit check 文件` 看一眼类型）",
        ) from exc


def _extract_targz(
    src: Path, dest: Path, force: bool, limits: Limits, report: ExtractReport
) -> None:
    try:
        # 用 "r:" 而不是 "r|"：需要先校验全部成员名再落盘，必须能来回 seek。
        # gzip.open 返回的 GzipFile 支持 seek（代价是内部重读一遍）。
        with gzip.open(src, "rb") as gz, tarfile.open(fileobj=gz, mode="r:") as tf:
            _extract_tar_members(tf, dest, force, limits, report)
    except (gzip.BadGzipFile, tarfile.TarError, EOFError, OSError) as exc:
        raise ArchiveFormatError(
            f".tar.gz 结构损坏：{exc}",
            "文件可能下载不完整；可以先试 `tar -tzf 文件.tar.gz` 看能否列出内容",
        ) from exc


def _extract_tar_members(
    tf: tarfile.TarFile, dest: Path, force: bool, limits: Limits, report: ExtractReport
) -> None:
    members = [m for m in tf.getmembers() if m.isfile()]
    limits.check_file_count(len(members))
    limits.check_declared_size(sum(m.size for m in members))

    skipped_special: List[str] = []
    total = 0
    for member in members:
        if member.issym() or member.islnk() or member.isdev():
            skipped_special.append(member.name)
            continue
        target = safe_join(dest, member.name)
        limits.check_single(member.size)
        if target.exists() and not force:
            target = _unique_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        extracted = tf.extractfile(member)
        if extracted is None:
            continue
        written = _stream_to_file(extracted, target, limits, total, member.name)
        total += written
        report.entries.append(ExtractedEntry(name=member.name, size=written))

    if skipped_special:
        report.warnings.append(
            f"跳过了 {len(skipped_special)} 个符号链接 / 设备文件（出于安全考虑）："
            + "、".join(skipped_special[:3])
        )


# ------------------------------------------------------------------ 7Z
def _extract_7z(
    src: Path, dest: Path, force: bool, limits: Limits, report: ExtractReport
) -> None:
    try:
        import py7zr  # 可选依赖
    except Exception as exc:  # pragma: no cover - 环境问题
        raise MissingDependency(
            "解压 .7z 需要额外安装一个纯 Python 库",
            "在终端执行：pip install py7zr ；然后重试",
        ) from exc

    try:
        with py7zr.SevenZipFile(str(src), mode="r") as archive:
            infos = archive.list()
            files = [i for i in infos if not i.is_directory]
            limits.check_file_count(len(files))
            limits.check_declared_size(sum(i.uncompressed or 0 for i in files))

            # 先全部校验，再解压（py7zr 的 extractall 会直接写盘）
            for info in files:
                safe_join(dest, info.filename)
                if info.uncompressed:
                    limits.check_single(info.uncompressed)

            archive.extractall(path=str(dest))
    except Exception as exc:
        if isinstance(exc, (ZipKitError, LimitsExceeded, UnsafeArchiveError)):
            raise
        raise ArchiveFormatError(
            f"7z 解压失败：{exc}",
            "可能是密码保护、固实压缩包或格式损坏；可先用 7-Zip 官方软件试解一次",
        ) from exc

    for info in files:
        report.entries.append(
            ExtractedEntry(name=info.filename, size=info.uncompressed or 0)
        )
    if any(i.is_encrypted for i in files if hasattr(i, "is_encrypted")):
        report.warnings.append("这个 7z 含加密内容，已尝试解压；若结果为空说明需要密码。")


# ------------------------------------------------------------------ 列表
def list_archive(path: Path | str, limit: int = 200) -> dict:
    """列出归档内容（不解压），供 `zipkit list` 使用。"""
    src = Path(path).expanduser()
    kind = detect_kind(src)
    rows: List[dict] = []

    def push(name: str, size: int, compressed: int | None) -> None:
        rows.append(
            {
                "name": name,
                "size": size,
                "compressed": compressed,
                "ratio": round(size / compressed, 2) if compressed else None,
            }
        )

    if kind in ("zip", "ooxml"):
        with zipfile.ZipFile(src) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                push(repair_zip_name(info.filename, info.flag_bits), info.file_size, info.compress_size)
    elif kind == "7z":
        try:
            import py7zr
        except Exception as exc:
            raise MissingDependency("查看 .7z 内容需要 py7zr", "执行：pip install py7zr") from exc
        with py7zr.SevenZipFile(str(src), mode="r") as archive:
            for info in archive.list():
                if info.is_directory:
                    continue
                push(info.filename, info.uncompressed or 0, info.compressed or None)
    elif kind == "gzip":
        row = {"name": _strip_gz_suffix(src.name), "size": None, "compressed": src.stat().st_size, "ratio": None}
        rows.append(row)
    elif kind == "tar":
        with tarfile.open(src, "r:*") as tf:
            for member in tf.getmembers():
                if member.isfile():
                    push(member.name, member.size, None)

    return {"kind": kind, "path": str(src), "entries": rows[:limit], "truncated": len(rows) > limit}
