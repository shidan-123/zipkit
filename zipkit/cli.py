"""命令行入口：`python -m zipkit <子命令>`。

刻意把每条错误都翻译成"发生了什么 + 你该做什么"两句话，
因为目标用户不是运维，看不懂 traceback。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from . import __version__
from .core import compress, extract, office
from .core.compress import LEVELS, check_files, pack
from .core.extract import extract as do_extract, list_archive
from .core.office import extract_text
from .core.safety import DEFAULT_LIMITS, Limits, human
from .errors import ZipKitError

# 终端宽度变化时表格不至于错位太多
_NAME_WIDTH = 42


def _short(text: str, width: int = _NAME_WIDTH) -> str:
    if len(text) <= width:
        return text
    return "…" + text[-(width - 1):]


def _bar(ratio: float, width: int = 12) -> str:
    filled = max(0, min(width, round(ratio * width)))
    return "█" * filled + "░" * (width - filled)


def _limits_from(args) -> Limits:
    mb = 1024 * 1024
    return Limits(
        max_files=args.max_files or DEFAULT_LIMITS.max_files,
        max_total=(args.max_total * mb) if args.max_total else DEFAULT_LIMITS.max_total,
        max_single=(args.max_single * mb) if args.max_single else DEFAULT_LIMITS.max_single,
        max_ratio=args.max_ratio or DEFAULT_LIMITS.max_ratio,
        ratio_floor_bytes=DEFAULT_LIMITS.ratio_floor_bytes,
    )


# ------------------------------------------------------------------ 各子命令
def cmd_pack(args) -> int:
    report = pack(
        args.files,
        out_path=args.output,
        level=args.level,
    )
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0

    print(f"\n📦 已生成：{report.out_path}")
    print(f"   {len(report.entries)} 个文件  {human(report.total_in)} → "
          f"{human(report.out_path.stat().st_size)}  "
          f"节省 {report.savings * 100:.1f}%  （耗时 {report.elapsed:.2f}s）\n")

    print(f"  {'文件':<{_NAME_WIDTH}} {'原始':>10} {'压缩后':>10} {'节省':>7}")
    print("  " + "-" * (_NAME_WIDTH + 32))
    for entry in report.entries[:20]:
        print(
            f"  {_short(entry.name):<{_NAME_WIDTH}} "
            f"{human(entry.size):>10} {human(entry.compressed):>10} "
            f"{entry.savings * 100:>6.1f}%"
        )
    if len(report.entries) > 20:
        print(f"  … 还有 {len(report.entries) - 20} 个文件未显示")

    for warning in report.warnings:
        print(f"\n  ⚠️  {warning}")
    return 0


def cmd_unpack(args) -> int:
    report = do_extract(
        args.archive, dest=args.dest, force=args.force, limits=_limits_from(args)
    )
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0

    print(f"\n📂 解压完成：{report.dest}")
    print(f"   {len(report.entries)} 个文件，共 {human(report.total_bytes)}，"
          f"格式 {report.kind}（耗时 {report.elapsed:.2f}s）")
    for entry in report.entries[:20]:
        print(f"   • {_short(entry.name, 60)}  {human(entry.size)}")
    if len(report.entries) > 20:
        print(f"   … 还有 {len(report.entries) - 20} 个文件")

    if report.skipped:
        print(f"\n   ⏭️  跳过 {len(report.skipped)} 项：{'、'.join(report.skipped[:5])}")
    for warning in report.warnings:
        print(f"\n   ⚠️  {warning}")
    return 0


def cmd_list(args) -> int:
    info = list_archive(args.archive)
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0

    print(f"\n🗂  {info['path']}   格式：{info['kind']}\n")
    if not info["entries"]:
        print("   （空归档）")
        return 0
    print(f"  {'文件':<{_NAME_WIDTH}} {'原始':>10} {'压缩后':>10}")
    print("  " + "-" * (_NAME_WIDTH + 24))
    for row in info["entries"]:
        size = human(row["size"]) if row["size"] is not None else "?"
        comp = human(row["compressed"]) if row["compressed"] else "?"
        print(f"  {_short(row['name']):<{_NAME_WIDTH}} {size:>10} {comp:>10}")
    if info["truncated"]:
        print(f"  … 内容过多，只显示前 {len(info['entries'])} 项")
    return 0


def cmd_text(args) -> int:
    text = extract_text(args.document)
    if args.output:
        Path(args.output).expanduser().write_text(text + "\n", encoding="utf-8")
        print(f"📝 文字已保存到：{args.output}（{len(text)} 个字符）")
    else:
        print(text)
    return 0


def cmd_check(args) -> int:
    rows = check_files(args.files)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    print()
    for row in rows:
        if "error" in row:
            print(f"  ❌ {row['path']}：{row['error']}")
            continue
        print(f"  📄 {Path(row['path']).name}")
        print(f"     类型：{row['kind']}")
        if "size" in row:
            print(f"     大小：{human(row['size'])}")
        print(f"     {row['note']}")
        if row.get("estimated_savings") is not None:
            ratio = row["estimated_savings"]
            print(f"     预估可压缩：{_bar(ratio)} {ratio * 100:.0f}%")
        print()
    return 0


def cmd_web(args) -> int:
    from .web.server import serve

    return serve(
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
        max_upload_mb=args.max_upload,
    )


# ------------------------------------------------------------------ 解析器
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zipkit",
        description="ZipKit —— 简单、安全的压缩 / 解压小工具",
        epilog="例：zipkit pack 报告.txt 数据.csv -o 打包.zip   |   zipkit unpack 打包.zip",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-V", "--version", action="version", version=f"ZipKit {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="子命令")

    p_pack = sub.add_parser("pack", help="把文件压缩成 .zip")
    p_pack.add_argument("files", nargs="+", help="要压缩的文件或目录")
    p_pack.add_argument("-o", "--output", help="输出文件（默认 zipkit-时间戳.zip）")
    p_pack.add_argument(
        "-l", "--level", choices=list(LEVELS), default="balanced",
        help="压缩级别：fast 快 / balanced 平衡（默认）/ max 最小",
    )
    p_pack.add_argument("--json", action="store_true", help="输出 JSON（给脚本用）")
    p_pack.set_defaults(func=cmd_pack)

    p_unpack = sub.add_parser("unpack", help="解压 zip / 7z / gz / tar.gz / docx / xlsx / pptx")
    p_unpack.add_argument("archive", help="要解压的文件")
    p_unpack.add_argument("-d", "--dest", help="解压到哪个目录（默认 <名字>_extracted）")
    p_unpack.add_argument("-f", "--force", action="store_true", help="同名文件直接覆盖（默认自动改名）")
    p_unpack.add_argument("--max-total", type=int, metavar="MB", help="解压总量上限（MB）")
    p_unpack.add_argument("--max-single", type=int, metavar="MB", help="单文件上限（MB）")
    p_unpack.add_argument("--max-files", type=int, help="文件数量上限")
    p_unpack.add_argument("--max-ratio", type=int, help="压缩比上限（防压缩炸弹）")
    p_unpack.add_argument("--json", action="store_true", help="输出 JSON")
    p_unpack.set_defaults(func=cmd_unpack)

    p_list = sub.add_parser("list", help="查看压缩包里有什么（不解压）")
    p_list.add_argument("archive")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_text = sub.add_parser("text", help="提取 docx / xlsx / pptx 里的文字")
    p_text.add_argument("document")
    p_text.add_argument("-o", "--output", help="保存到文件（默认打印到屏幕）")
    p_text.set_defaults(func=cmd_text)

    p_check = sub.add_parser("check", help="体检：识别类型 + 预估能压多少")
    p_check.add_argument("files", nargs="+")
    p_check.add_argument("--json", action="store_true")
    p_check.set_defaults(func=cmd_check)

    p_web = sub.add_parser("web", help="启动本地网页界面（推荐新手用）")
    p_web.add_argument("--port", type=int, default=8765, help="端口（默认 8765）")
    p_web.add_argument("--host", default="127.0.0.1", help="监听地址（默认只允许本机）")
    p_web.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    p_web.add_argument("--max-upload", type=int, default=64, metavar="MB", help="单次上传上限（MB）")
    p_web.set_defaults(func=cmd_web)

    return parser


_BANNER = f"""\
╭──────────────────────────────────────────────╮
│  ZipKit {__version__}  ·  压缩 / 解压，说人话        │
╰──────────────────────────────────────────────╯
  新手建议直接跑：  python -m zipkit web
  然后浏览器里拖文件进去，不用记命令。
"""


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        print(_BANNER)
        parser.print_help()
        return 0

    try:
        return int(args.func(args) or 0)
    except ZipKitError as exc:
        print(f"\n❌ {exc.message}", file=sys.stderr)
        if exc.hint:
            print(f"   → {exc.hint}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        return 130
    except BrokenPipeError:  # 例如 `| head`
        return 0
    except Exception as exc:  # 未预料的 bug
        print(f"\n❌ 出了个没预料到的错：{exc!r}", file=sys.stderr)
        print("   → 这是程序缺陷，请把上面这行连同操作步骤发到 GitHub Issues", file=sys.stderr)
        return 2
