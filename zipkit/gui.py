"""ZipKit 大文件版 —— 独立的桌面窗口（Tkinter），与网页版互不影响。

为什么单独做一个：
网页版要把文件转成 Base64 塞进请求，会膨胀 33% 且全在内存里，所以只能到 64 MB。
这个版本直接在硬盘上流式读写：**上限只取决于你的磁盘空间**。

为什么用 Tkinter：
它是 Python 自带的，不用 pip 安装、不用打包成 exe 就能跑；
界面朴素但足够，而且三个系统行为一致。
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

from . import __version__
from .core.compress import LEVELS, pack
from .core.extract import extract
from .core.safety import Limits, human
from .errors import ZipKitError

# 关窗口时如果还在跑任务，提示用户
_APP_TITLE = f"ZipKit 大文件版  v{__version__}"


class ZipKitApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(_APP_TITLE)
        self.geometry("780x680")
        self.minsize(700, 620)

        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._busy = False
        self._pack_files: List[Path] = []
        self._pb_mode = "determinate"

        self._build_style()
        self._build_layout()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._drain_queue)

    # ------------------------------------------------------------ 外观
    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")  # macOS 上比默认主题间距更正常
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("PingFang SC", 20, "bold"))
        style.configure("Sub.TLabel", foreground="#6b7280")
        style.configure("Go.TButton", font=("PingFang SC", 13, "bold"))
        style.configure("Hint.TLabel", foreground="#6b7280")

    def _build_layout(self) -> None:
        root = ttk.Frame(self, padding=18)
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root)
        header.pack(fill="x", pady=(0, 4))
        ttk.Label(header, text="ZipKit", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="  大文件版", style="Sub.TLabel").pack(side="left", pady=(8, 0))
        ttk.Label(
            header,
            text="不转 Base64、不占内存，边读边写 · 上限只看磁盘剩余空间",
            style="Hint.TLabel",
        ).pack(side="right", pady=(10, 0))

        self.tabs = ttk.Notebook(root)
        self.tabs.pack(fill="both", expand=True, pady=(10, 0))

        self._build_pack_tab()
        self._build_unpack_tab()

        # 共享的结果区
        result_frame = ttk.LabelFrame(root, text=" 结果 / 日志 ", padding=8)
        result_frame.pack(fill="both", expand=True, pady=(12, 0))
        self.log = tk.Text(result_frame, height=8, wrap="word", state="disabled",
                           font=("Menlo", 11), relief="flat", padx=6, pady=4)
        scroll = ttk.Scrollbar(result_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    # ------------------------------------------------------------ 压缩页
    def _build_pack_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=14)
        self.tabs.add(tab, text="  压缩  ")

        ttk.Label(
            tab,
            text="选中文件或整个文件夹，压缩成一个 .zip（文本、日志、CSV、JSON、BMP、WAV、TIFF）",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(0, 8))

        list_frame = ttk.Frame(tab)
        list_frame.pack(fill="both", expand=True)
        self.file_list = tk.Listbox(list_frame, height=7, activestyle="none",
                                    font=("Menlo", 11), relief="solid", borderwidth=1)
        lscroll = ttk.Scrollbar(list_frame, command=self.file_list.yview)
        self.file_list.configure(yscrollcommand=lscroll.set)
        self.file_list.pack(side="left", fill="both", expand=True)
        lscroll.pack(side="right", fill="y")

        btns = ttk.Frame(tab)
        btns.pack(fill="x", pady=8)
        ttk.Button(btns, text="添加文件…", command=self._pick_files).pack(side="left")
        ttk.Button(btns, text="添加文件夹…", command=self._pick_folder).pack(side="left", padx=6)
        ttk.Button(btns, text="清空", command=self._clear_files).pack(side="left")
        self.pack_summary = ttk.Label(btns, text="未选择任何文件", style="Hint.TLabel")
        self.pack_summary.pack(side="right")

        opts = ttk.Frame(tab)
        opts.pack(fill="x", pady=4)
        ttk.Label(opts, text="压缩级别").pack(side="left")
        self.level_var = tk.StringVar(value="balanced")
        ttk.Combobox(
            opts, textvariable=self.level_var, state="readonly", width=10,
            values=["fast", "balanced", "max"],
        ).pack(side="left", padx=(6, 20))
        ttk.Label(opts, text="输出文件").pack(side="left")
        self.out_var = tk.StringVar()
        ttk.Entry(opts, textvariable=self.out_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(opts, text="另存为…", command=self._pick_out).pack(side="left")

        self.pack_btn = ttk.Button(tab, text="开始压缩", style="Go.TButton", command=self._start_pack)
        self.pack_btn.pack(fill="x", pady=(14, 8), ipady=6)

        self.pack_pb = ttk.Progressbar(tab, mode="determinate", maximum=100)
        self.pack_pb.pack(fill="x")
        self.pack_status = ttk.Label(tab, text="就绪", style="Hint.TLabel")
        self.pack_status.pack(anchor="w", pady=(4, 0))

    # ------------------------------------------------------------ 解压页
    def _build_unpack_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=14)
        self.tabs.add(tab, text="  解压  ")

        ttk.Label(
            tab,
            text="支持 .zip / .7z / .gz / .tar.gz / .tgz / .tar / .docx / .xlsx / .pptx",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(0, 10))

        row1 = ttk.Frame(tab)
        row1.pack(fill="x", pady=4)
        ttk.Label(row1, text="压缩包").pack(side="left")
        self.archive_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.archive_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row1, text="浏览…", command=self._pick_archive).pack(side="left")

        row2 = ttk.Frame(tab)
        row2.pack(fill="x", pady=4)
        ttk.Label(row2, text="解压到").pack(side="left")
        self.dest_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.dest_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row2, text="浏览…", command=self._pick_dest).pack(side="left")

        ttk.Label(
            tab,
            text="提示：默认解到「压缩包名_extracted」文件夹；同名文件会自动改名，不会覆盖。",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(8, 0))

        self.unpack_btn = ttk.Button(tab, text="开始解压", style="Go.TButton", command=self._start_unpack)
        self.unpack_btn.pack(fill="x", pady=(18, 8), ipady=6)

        self.unpack_pb = ttk.Progressbar(tab, mode="determinate", maximum=100)
        self.unpack_pb.pack(fill="x")
        self.unpack_status = ttk.Label(tab, text="就绪", style="Hint.TLabel")
        self.unpack_status.pack(anchor="w", pady=(4, 0))

        open_row = ttk.Frame(tab)
        open_row.pack(fill="x", pady=(12, 0))
        ttk.Button(open_row, text="打开输出文件夹", command=self._open_output).pack(side="left")

    # ------------------------------------------------------------ 选择器
    def _pick_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择要压缩的文件",
            filetypes=[
                ("推荐的格式", "*.txt *.log *.csv *.json *.bmp *.wav *.tiff *.tif"),
                ("所有文件", "*.*"),
            ],
        )
        for item in paths:
            p = Path(item)
            if p not in self._pack_files:
                self._pack_files.append(p)
        self._refresh_file_list()

    def _pick_folder(self) -> None:
        folder = filedialog.askdirectory(title="选择要压缩的文件夹")
        if folder:
            p = Path(folder)
            if p not in self._pack_files:
                self._pack_files.append(p)
            self._refresh_file_list()

    def _clear_files(self) -> None:
        self._pack_files.clear()
        self._refresh_file_list()

    def _refresh_file_list(self) -> None:
        self.file_list.delete(0, "end")
        total = 0
        for p in self._pack_files:
            if p.is_dir():
                self.file_list.insert("end", f"📁 {p.name}/")
            else:
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
                self.file_list.insert("end", f"📄 {p.name}")

        count = len(self._pack_files)
        self.pack_summary.config(
            text=f"{count} 项，共 {human(total)}" if count else "未选择任何文件"
        )
        if count and not self.out_var.get():
            first = self._pack_files[0]
            base = first.name if first.is_dir() else first.stem
            self.out_var.set(str(first.parent / f"{base}-打包.zip"))

    def _pick_out(self) -> None:
        path = filedialog.asksaveasfilename(
            title="保存为", defaultextension=".zip",
            filetypes=[("ZIP 压缩包", "*.zip")], initialfile="打包.zip",
        )
        if path:
            self.out_var.set(path)

    def _pick_archive(self) -> None:
        path = filedialog.askopenfilename(
            title="选择压缩包",
            filetypes=[
                ("压缩包 / 文档", "*.zip *.7z *.gz *.tgz *.tar *.docx *.xlsx *.pptx"),
                ("所有文件", "*.*"),
            ],
        )
        if path:
            self.archive_var.set(path)
            p = Path(path)
            base = p.name
            for compound in (".tar.gz", ".tgz"):
                if base.lower().endswith(compound):
                    base = base[: -len(compound)]
                    break
            else:
                base = p.stem
            self.dest_var.set(str(p.parent / f"{base}_extracted"))

    def _pick_dest(self) -> None:
        folder = filedialog.askdirectory(title="选择解压到的文件夹")
        if folder:
            self.dest_var.set(folder)

    def _open_output(self) -> None:
        target = self.dest_var.get() or self.out_var.get()
        if not target:
            messagebox.showinfo("没有输出", "还没开始任务，或者任务没有产生结果。")
            return
        path = Path(target)
        if not path.exists():
            messagebox.showinfo("还没有结果", "先点「开始解压/压缩」，完成后才有输出。")
            return
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", str(path)], check=False)
            elif os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception as exc:  # pragma: no cover - 平台差异
            messagebox.showerror("打不开", f"{exc}")

    # ------------------------------------------------------------ 任务执行
    def _start_pack(self) -> None:
        if self._busy:
            return
        if not self._pack_files:
            messagebox.showinfo("先选文件", "点左边的「添加文件…」或「添加文件夹…」。")
            return

        out = self.out_var.get().strip()
        if not out:
            messagebox.showinfo("缺少输出路径", "点「另存为…」选一个保存位置，或直接开始（会自动生成）。")
            return

        inputs = list(self._pack_files)
        level = self.level_var.get()
        self._begin("pack")

        def work() -> None:
            try:
                def on_progress(index: int, total: int, name: str) -> None:
                    self._queue.put(("pack_progress", index, total, name))

                report = pack(inputs, out_path=out, level=level, progress=on_progress)
                self._queue.put(("pack_done", report))
            except ZipKitError as exc:
                self._queue.put(("error", exc.message, exc.hint))
            except Exception as exc:  # pragma: no cover
                self._queue.put(("error", f"未预料的错误：{exc!r}", ""))

        threading.Thread(target=work, daemon=True).start()

    def _start_unpack(self) -> None:
        if self._busy:
            return
        archive = self.archive_var.get().strip()
        if not archive:
            messagebox.showinfo("先选压缩包", "点「浏览…」选一个要解压的文件。")
            return

        dest = self.dest_var.get().strip() or None
        self._begin("unpack")

        def work() -> None:
            try:
                def on_progress(name: str, done: int, total: Optional[int]) -> None:
                    self._queue.put(("unpack_progress", name, done, total))

                report = extract(archive, dest=dest, progress=on_progress)
                self._queue.put(("unpack_done", report))
            except ZipKitError as exc:
                self._queue.put(("error", exc.message, exc.hint))
            except Exception as exc:  # pragma: no cover
                self._queue.put(("error", f"未预料的错误：{exc!r}", ""))

        threading.Thread(target=work, daemon=True).start()

    def _begin(self, kind: str) -> None:
        self._busy = True
        self.pack_btn.config(state="disabled")
        self.unpack_btn.config(state="disabled")
        pb = self.pack_pb if kind == "pack" else self.unpack_pb
        pb.config(mode="determinate", maximum=100, value=0)
        self._set_status(kind, "准备中…")
        self._log_clear()
        self._log("开始处理，请稍候（大文件可能需要几分钟）…\n")

    # ------------------------------------------------------------ 队列泵
    def _drain_queue(self) -> None:
        try:
            while True:
                msg = self._queue.get_nowait()
                self._handle_message(msg)
        except queue.Empty:
            pass
        self.after(80, self._drain_queue)

    def _handle_message(self, msg: tuple) -> None:
        kind = msg[0]

        if kind == "pack_progress":
            _, index, total, name = msg
            self.pack_pb.config(mode="determinate", maximum=max(total, 1), value=index)
            self._set_status("pack", f"正在压缩 {index}/{total}：{name}")

        elif kind == "unpack_progress":
            _, name, done, total = msg
            if total:
                self.unpack_pb.config(mode="determinate", maximum=max(total, 1), value=done)
                percent = done * 100 / total
                self._set_status("unpack", f"{percent:.0f}%  {name}（{human(done)} / {human(total)}）")
            else:
                self._set_status("unpack", f"正在解压 {name}（已写 {human(done)}）")

        elif kind == "pack_done":
            report = msg[1]
            self._finish()
            self.pack_pb.config(mode="determinate", maximum=100, value=100)
            self._set_status("pack", f"完成：{human(report.total_in)} → {human(report.out_path.stat().st_size)}")
            self._log(f"\n✅ 已生成：{report.out_path}")
            self._log(f"   {len(report.entries)} 个文件，"
                      f"{human(report.total_in)} → {human(report.out_path.stat().st_size)}，"
                      f"节省 {report.savings * 100:.1f}%（耗时 {report.elapsed:.1f}s）")
            for warning in report.warnings:
                self._log(f"   ⚠️  {warning}")

        elif kind == "unpack_done":
            report = msg[1]
            self._finish()
            self.unpack_pb.config(mode="determinate", maximum=100, value=100)
            self._set_status("unpack", f"完成：{len(report.entries)} 个文件")
            self._log(f"\n✅ 解压完成：{report.dest}")
            self._log(f"   {len(report.entries)} 个文件，共 {human(report.total_bytes)}，"
                      f"格式 {report.kind}（耗时 {report.elapsed:.1f}s）")
            for entry in report.entries[:15]:
                self._log(f"   • {entry.name}  {human(entry.size)}")
            if len(report.entries) > 15:
                self._log(f"   … 还有 {len(report.entries) - 15} 个")
            for warning in report.warnings:
                self._log(f"   ⚠️  {warning}")

        elif kind == "error":
            _, message, hint = msg
            self._finish()
            self._set_status("pack", "出错了")
            self._set_status("unpack", "出错了")
            self._log(f"\n❌ {message}")
            if hint:
                self._log(f"   → {hint}")
            messagebox.showerror("处理失败", f"{message}\n\n{hint}" if hint else message)

    def _finish(self) -> None:
        self._busy = False
        self.pack_btn.config(state="normal")
        self.unpack_btn.config(state="normal")

    # ------------------------------------------------------------ 小工具
    def _set_status(self, kind: str, text: str) -> None:
        label = self.pack_status if kind == "pack" else self.unpack_status
        label.config(text=text)

    def _log(self, text: str) -> None:
        self.log.config(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _log_clear(self) -> None:
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    def _on_close(self) -> None:
        if self._busy and not messagebox.askyesno("还在处理中", "任务还没完成，确定要退出吗？"):
            return
        self.destroy()


def main(argv: Optional[List[str]] = None) -> int:
    """启动窗口。返回退出码，供 CLI 使用。"""
    # Tk 8.5 在 macOS 26 上会直接 abort（连异常都来不及抛），必须先拦
    if tk.TkVersion < 8.6:
        raise ZipKitError(
            f"当前 Python 自带的是 Tk {tk.TkVersion}，在新版 macOS 上无法开窗口",
            "请用官方的 Python 3.13（自带 Tk 8.6）运行：https://www.python.org/downloads/ ；"
            "或者直接用命令行：python3 -m zipkit unpack 文件名",
        )

    try:
        app = ZipKitApp()
    except Exception as exc:  # 例如 tkinter 缺失、Tk 版本过老
        raise ZipKitError(
            f"图形界面启动失败：{exc}",
            "macOS 上请用 python.org 安装的 Python 3.13 运行（自带 Tk 8.6）；"
            "也可以改用命令行：python3 -m zipkit unpack 文件名",
        ) from exc
    app.mainloop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
