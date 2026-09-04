"""照片传输 GUI 模块 — tkinter 实现。

与后端模块完全解耦，通过 lib/reporter.py 接口通信。
进度条按累计下载字节驱动；大文件下载中实时刷新。
"""

import sys
import os
import json
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog

# 确保项目根目录在 sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from lib.reporter import ProgressReporter
from lib.orchestrator import SyncWorker

CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")

# --- 配色（现代简洁风）---
COLORS = {
    "bg": "#eef1f7",
    "card": "#ffffff",
    "accent": "#4f6df5",
    "accent_dark": "#3b53d6",
    "accent_soft": "#e7ecff",
    "text": "#1f2733",
    "muted": "#8a93a5",
    "success": "#22c55e",
    "danger": "#ef4444",
    "border": "#e2e6f0",
}


def _fmt_size(n: int) -> str:
    if n < 1024 ** 2:
        return f"{n / 1024:.0f} KB"
    elif n < 1024 ** 3:
        return f"{n / (1024 ** 2):.1f} MB"
    else:
        return f"{n / (1024 ** 3):.2f} GB"


def _configure_style(root: tk.Tk) -> None:
    """应用统一的现代样式。"""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure("App.TFrame", background=COLORS["bg"])
    style.configure("Card.TFrame", background=COLORS["card"])
    style.configure("Card.TLabel", background=COLORS["card"], foreground=COLORS["text"])
    style.configure("Muted.TLabel", background=COLORS["card"], foreground=COLORS["muted"])
    style.configure("Accent.TLabel", background=COLORS["card"], foreground=COLORS["accent"])

    style.configure("Header.TLabel", background=COLORS["accent"], foreground="#ffffff",
                    font=("Segoe UI", 16, "bold"))
    style.configure("HeaderSub.TLabel", background=COLORS["accent"], foreground="#dfe6ff",
                    font=("Segoe UI", 10))

    style.configure("Title.TLabel", background=COLORS["bg"], foreground=COLORS["text"],
                    font=("Segoe UI", 11, "bold"))
    style.configure("Body.TLabel", background=COLORS["bg"], foreground=COLORS["muted"],
                    font=("Segoe UI", 10))

    # 按钮
    style.configure("Accent.TButton", background=COLORS["accent"],
                    foreground="#ffffff", borderwidth=0, focuscolor=COLORS["accent"],
                    padding=(18, 8), font=("Segoe UI", 10, "bold"))
    style.map("Accent.TButton", background=[("disabled", "#b9c3f5"),
                                            ("active", COLORS["accent_dark"]),
                                            ("pressed", COLORS["accent_dark"])])
    style.configure("Ghost.TButton", background=COLORS["card"], foreground=COLORS["text"],
                    borderwidth=1, bordercolor=COLORS["border"], padding=(18, 8),
                    font=("Segoe UI", 10))
    style.map("Ghost.TButton", background=[("active", COLORS["accent_soft"])])

    # 进度条（clam 主题支持自定义填充色）
    style.configure("Accent.Horizontal.TProgressbar",
                    troughcolor=COLORS["border"], background=COLORS["accent"],
                    bordercolor=COLORS["border"], lightcolor=COLORS["accent"],
                    darkcolor=COLORS["accent"])

    # 目录输入框
    style.configure("Dir.TEntry", fieldbackground="#ffffff", bordercolor=COLORS["border"],
                    foreground=COLORS["text"], padding=(8, 5))
    style.map("Dir.TEntry", bordercolor=[("focus", COLORS["accent"])])

    # 标签框
    style.configure("Card.TLabelframe", background=COLORS["card"], bordercolor=COLORS["border"])
    style.configure("Card.TLabelframe.Label", background=COLORS["card"],
                    foreground=COLORS["accent"], font=("Segoe UI", 10, "bold"))


class GuiReporter:
    """实现 ProgressReporter 协议，更新 tkinter 控件。"""

    def __init__(self, root: tk.Tk, log: scrolledtext.ScrolledText,
                 progress_bar: ttk.Progressbar, percent_label: tk.StringVar,
                 file_label: tk.StringVar, stats_label: tk.StringVar,
                 status_label: tk.StringVar):
        self.root = root
        self.log = log
        self.progress_bar = progress_bar
        self.percent_label = percent_label
        self.file_label = file_label
        self.stats_label = stats_label
        self.status_label = status_label
        self.total_bytes = 1  # 避免除零；on_download_start 会更新
        self._max_downloaded = 0  # 防止并发下进度条回退

    def _run(self, fn):
        """线程安全地将回调提交到 tkinter 主线程。"""
        self.root.after(0, fn)

    def _append_log(self, text: str) -> None:
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)

    def on_scan_start(self, total_dirs: int) -> None:
        self._run(lambda: self._append_log(f"开始扫描 {total_dirs} 个目录..."))

    def on_scan_progress(self, current_dir: str, files_found: int) -> None:
        self._run(lambda: self.status_label.set(f"扫描: {current_dir} ({files_found} 张)"))

    def on_diff_result(self, total_phone: int, new_count: int, conflict_count: int,
                       download_size_gb: float) -> None:
        self._run(lambda: (
            self._append_log(
                f"手机照片: {total_phone}  新增: {new_count}  " 
                f"待下载: {download_size_gb:.2f} GB"
            ),
            self.stats_label.set(f"{new_count} 个新文件 · {download_size_gb:.2f} GB")
        ))

    def on_download_start(self, total_files: int, total_bytes: int) -> None:
        self.total_bytes = max(total_bytes, 1)
        self._max_downloaded = 0
        self._run(lambda: (
            self.progress_bar.configure(value=0, maximum=self.total_bytes),
            self.percent_label.set("0.0%"),
            self._append_log(f"开始下载 {total_files} 个文件 ({_fmt_size(self.total_bytes)})")
        ))

    def on_download_progress(self, index: int, total: int, filename: str,
                             speed_mbps: float, remaining_minutes: int,
                             downloaded_bytes: int) -> None:
        self._run(lambda: self._update_download_widgets(
            index, total, filename, speed_mbps, remaining_minutes, downloaded_bytes))

    def _update_download_widgets(self, index: int, total: int, filename: str,
                                 speed_mbps: float, remaining_minutes: int,
                                 downloaded_bytes: int) -> None:
        # 并发下实时上报可能短暂回退，用历史最大值保证进度条只前进
        self._max_downloaded = max(self._max_downloaded, downloaded_bytes)
        shown = min(self._max_downloaded, self.total_bytes)
        self.progress_bar.configure(value=shown)
        pct = min(100.0, shown / self.total_bytes * 100.0)
        self.percent_label.set(f"{pct:.1f}%")
        self.file_label.set(f"[{index}/{total}] {filename}")
        self.status_label.set(
            f"{speed_mbps:.1f} MB/s · 剩余约 {remaining_minutes} 分钟 · "
            f"{_fmt_size(shown)} / {_fmt_size(self.total_bytes)}"
        )

    def on_download_file_error(self, filename: str, error: str) -> None:
        self._run(lambda: self._append_log(f"  ✗ {filename}: {error}"))

    def on_download_complete(self, success: int, failed: int, duration_secs: float) -> None:
        mins = int(duration_secs // 60)
        secs = int(duration_secs % 60)
        self._run(lambda: (
            self._append_log(f"\n同步完成! {success} 成功, {failed} 失败, 耗时 {mins}分{secs}秒"),
            self.percent_label.set("100.0%"),
            self.progress_bar.configure(value=self.total_bytes),
            self.status_label.set("就绪"),
            self.stats_label.set(f"{success} 成功 · {failed} 失败")
        ))

    def on_status(self, message: str) -> None:
        self._run(lambda: (
            self.status_label.set(message),
            self._append_log(message)
        ))

    def on_error(self, message: str) -> None:
        self._run(lambda: (
            self._append_log(f"错误: {message}"),
            messagebox.showerror("错误", message)
        ))


class PhotoSyncApp:
    """照片传输 GUI 主窗口。"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("照片/视频传输工具")
        self.root.geometry("760x620")
        self.root.minsize(680, 560)
        self.root.configure(background=COLORS["bg"])
        _configure_style(self.root)

        self._worker: SyncWorker | None = None
        self._build_ui()
        self._load_config()
        # 窗口关闭时取消同步并终止后台 adb 子进程，干净退出
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        root = self.root

        # 顶部横幅
        banner = tk.Frame(root, background=COLORS["accent"])
        banner.pack(fill=tk.X)
        tk.Label(banner, text="照片 / 视频传输工具", background=COLORS["accent"],
                 foreground="#ffffff", font=("Segoe UI", 16, "bold")).pack(
            anchor=tk.W, padx=18, pady=(12, 2))
        tk.Label(banner, text="通过 USB 从手机同步到电脑", background=COLORS["accent"],
                 foreground="#dfe6ff", font=("Segoe UI", 10)).pack(
            anchor=tk.W, padx=18, pady=(0, 12))

        content = ttk.Frame(root, style="App.TFrame")
        content.pack(fill=tk.BOTH, expand=True, padx=16, pady=14)

        # 目标目录卡片（可编辑 + 浏览选择 + 保存）
        cfg_card = ttk.LabelFrame(content, text="目标目录", style="Card.TLabelframe", padding=14)
        cfg_card.pack(fill=tk.X)
        grid = ttk.Frame(cfg_card, style="Card.TFrame")
        grid.pack(fill=tk.X)
        grid.columnconfigure(1, weight=1)

        ttk.Label(grid, text="照片目录", style="Muted.TLabel").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.photo_var = tk.StringVar()
        photo_entry = ttk.Entry(grid, textvariable=self.photo_var, style="Dir.TEntry")
        photo_entry.grid(row=0, column=1, sticky=tk.EW, padx=(10, 4), pady=4)
        ttk.Button(grid, text="浏览…", style="Ghost.TButton",
                   command=lambda: self._browse_dir(self.photo_var)).grid(
            row=0, column=2, sticky=tk.W)

        ttk.Label(grid, text="视频目录", style="Muted.TLabel").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.video_var = tk.StringVar()
        video_entry = ttk.Entry(grid, textvariable=self.video_var, style="Dir.TEntry")
        video_entry.grid(row=1, column=1, sticky=tk.EW, padx=(10, 4), pady=4)
        ttk.Button(grid, text="浏览…", style="Ghost.TButton",
                   command=lambda: self._browse_dir(self.video_var)).grid(
            row=1, column=2, sticky=tk.W)

        ttk.Button(cfg_card, text="保存目录", style="Accent.TButton",
                   command=self._save_config).pack(anchor=tk.E, pady=(10, 0))

        # 同步状态卡片
        stat_card = ttk.LabelFrame(content, text="同步状态", style="Card.TLabelframe", padding=14)
        stat_card.pack(fill=tk.X, pady=(14, 0))

        self.stats_label = tk.StringVar(value="等待开始...")
        ttk.Label(stat_card, textvariable=self.stats_label,
                  style="Title.TLabel").pack(anchor=tk.W)

        # 进度条 + 百分比
        prog_row = ttk.Frame(stat_card, style="Card.TFrame")
        prog_row.pack(fill=tk.X, pady=(12, 0))
        prog_row.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(prog_row, style="Accent.Horizontal.TProgressbar",
                                        mode="determinate")
        self.progress.grid(row=0, column=0, sticky=tk.EW)

        self.percent_label = tk.StringVar(value="0.0%")
        ttk.Label(prog_row, textvariable=self.percent_label,
                  style="Accent.TLabel", width=7, anchor=tk.E).grid(
            row=0, column=1, padx=(12, 0))

        self.file_label = tk.StringVar(value="等待开始...")
        ttk.Label(stat_card, textvariable=self.file_label,
                  style="Body.TLabel").pack(anchor=tk.W, pady=(10, 0))

        self.status_label = tk.StringVar(value="就绪")
        ttk.Label(stat_card, textvariable=self.status_label,
                  style="Muted.TLabel").pack(anchor=tk.W, pady=(2, 0))

        # 操作按钮
        btn_row = ttk.Frame(content, style="App.TFrame")
        btn_row.pack(fill=tk.X, pady=(14, 0))

        self.btn_photo = ttk.Button(btn_row, text="同步照片", style="Accent.TButton",
                                    command=lambda: self._start_sync("photo"))
        self.btn_photo.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_video = ttk.Button(btn_row, text="同步视频", style="Accent.TButton",
                                    command=lambda: self._start_sync("video"))
        self.btn_video.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_cancel = ttk.Button(btn_row, text="取消", style="Ghost.TButton",
                                     command=self._cancel_sync, state=tk.DISABLED)
        self.btn_cancel.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_explore = ttk.Button(btn_row, text="探索设备", style="Ghost.TButton",
                                      command=self._explore_device)
        self.btn_explore.pack(side=tk.LEFT)

        # 日志区域
        log_card = ttk.LabelFrame(content, text="日志", style="Card.TLabelframe", padding=14)
        log_card.pack(fill=tk.BOTH, expand=True, pady=(14, 0))

        self.log = scrolledtext.ScrolledText(
            log_card, height=12, wrap=tk.WORD, relief=tk.FLAT,
            background="#f9fafc", foreground=COLORS["text"],
            font=("Consolas", 9), padx=8, pady=6, insertbackground=COLORS["accent"])
        self.log.pack(fill=tk.BOTH, expand=True)

    def _load_config(self) -> None:
        """加载配置（填充目录输入框）。"""
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                config = json.load(fh)
            self.config = config
            self.photo_var.set(config.get("pc_photo_dir",
                config.get("pc_target_dir", "D:/个人/相片")))
            self.video_var.set(config.get("pc_video_dir", "D:/个人/视频"))
        except Exception:
            self.config = {"pc_photo_dir": "D:/个人/相片", "pc_video_dir": "D:/个人/视频"}
            self.photo_var.set(self.config["pc_photo_dir"])
            self.video_var.set(self.config["pc_video_dir"])

    def _browse_dir(self, var: tk.StringVar) -> None:
        """弹目录选择框，并把选中路径写入 StringVar。"""
        initial = var.get().strip() or os.path.expanduser("~")
        path = filedialog.askdirectory(initialdir=initial, title="选择目录")
        if path:
            var.set(path)

    def _save_config(self) -> None:
        """把当前目录输入框内容写回 config.json（保留其他字段）。"""
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                cfg = json.load(fh)
        except Exception:
            cfg = {}
        cfg["pc_photo_dir"] = self.photo_var.get().strip()
        cfg["pc_video_dir"] = self.video_var.get().strip()
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
        self.config = cfg
        self._append_log(f"目录配置已保存：照片={cfg['pc_photo_dir']} 视频={cfg['pc_video_dir']}")
        messagebox.showinfo("保存成功", "目标目录已保存到 config.json")

    def _start_sync(self, mode: str) -> None:
        """启动同步（后台线程）。

        Args:
            mode: "photo" 或 "video"
        """
        self.btn_photo.configure(state=tk.DISABLED)
        self.btn_video.configure(state=tk.DISABLED)
        self.btn_cancel.configure(state=tk.NORMAL)
        self.progress.configure(value=0, maximum=100)
        self.percent_label.set("0.0%")
        self.file_label.set("正在准备...")
        self.stats_label.set("—")

        reporter = GuiReporter(
            self.root, self.log, self.progress, self.percent_label,
            self.file_label, self.stats_label, self.status_label
        )

        photo_dir = self.photo_var.get().strip() or self.config.get("pc_photo_dir",
            self.config.get("pc_target_dir", "D:/个人/相片"))
        video_dir = self.video_var.get().strip() or self.config.get("pc_video_dir", "D:/个人/视频")
        self._worker = SyncWorker(photo_dir, video_dir, reporter, mode=mode)
        self._worker.start()
        self._poll_worker()

    def _poll_worker(self) -> None:
        """轮询工作线程完成状态。"""
        if self._worker and self._worker.is_running():
            self.root.after(200, self._poll_worker)
        else:
            self.btn_photo.configure(state=tk.NORMAL)
            self.btn_video.configure(state=tk.NORMAL)
            self.btn_cancel.configure(state=tk.DISABLED)

    def _cancel_sync(self) -> None:
        """取消同步。"""
        if self._worker:
            self._worker.cancel()
            self._append_log("正在取消...")
            self.btn_cancel.configure(state=tk.DISABLED)

    def _on_close(self) -> None:
        """窗口关闭：取消同步并终止后台 adb 子进程，随后退出。"""
        if self._worker:
            self._worker.cancel()
        self.root.destroy()

    def _explore_device(self) -> None:
        """探索设备信息。"""
        try:
            from modules import load_module
            m1 = load_module("adb_connector", "device")
            device = m1.check_device()
            info = m1.get_device_info(device)
            self._append_log(f"设备: {info['model']} (Android {info['android_version']})")
            self._append_log(f"/sdcard/ 目录:")
            for d in sorted(info["storage_roots"]):
                self._append_log(f"  {d}/")
        except Exception as e:
            self._append_log(f"探索失败: {e}")
            messagebox.showerror("错误", str(e))

    def _append_log(self, text: str) -> None:
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)

    def run(self) -> None:
        self.root.mainloop()


def main():
    app = PhotoSyncApp()
    app.run()


if __name__ == "__main__":
    main()
