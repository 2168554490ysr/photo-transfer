"""同步编排器——在后台线程运行完整同步流程。

依赖 lib/reporter.py 协议，不依赖任何具体 UI。
"""

import os
import json
import threading
import time
from typing import Optional

from modules import load_module
from lib.reporter import ProgressReporter


class SyncWorker:
    """后台同步工作线程。

    用法:
        reporter = MyGUIReporter(...)
        worker = SyncWorker(photo_dir, video_dir, reporter)
        worker.start()  # 非阻塞，在后台线程运行
    """

    def __init__(self, photo_dir: str, video_dir: str, reporter: ProgressReporter,
                 mode: str = "all"):
        """Args:
            photo_dir: PC 照片目录
            video_dir: PC 视频目录
            reporter: 进度报告器
            mode: "photo" / "video" / "all"
        """
        self.photo_dir = photo_dir
        self.video_dir = video_dir
        self.reporter = reporter
        self.mode = mode
        self._thread: Optional[threading.Thread] = None
        self._cancel_flag = threading.Event()

    def start(self) -> None:
        """启动后台同步（非阻塞）。"""
        if self._thread and self._thread.is_alive():
            return
        self._cancel_flag.clear()
        # 清除上次取消标志，使新一轮同步可正常执行 adb
        try:
            m1 = load_module("adb_connector", "device")
            m1.reset_cancel()
        except Exception:
            pass
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        """请求取消同步，并终止正在运行的 adb 子进程（关闭窗口时干净退出）。"""
        self._cancel_flag.set()
        try:
            m1 = load_module("adb_connector", "device")
            m1.kill_all_adb()
        except Exception:
            pass

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _get_verify_conflicts(self) -> bool:
        """读取 config.json 的 verify_conflicts 开关（缺省 False = 默认跳过哈希）。"""
        try:
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            with open(os.path.join(root, "config.json"), "r", encoding="utf-8") as fh:
                return bool(json.load(fh).get("verify_conflicts", False))
        except Exception:
            return False

    def _run(self) -> None:
        """后台线程主逻辑——同步照片 + 视频。"""
        try:
            m1 = load_module("adb_connector", "device")
            m2 = load_module("photo_scanner", "scanner")
            m3 = load_module("photo_downloader", "downloader")

            # 检测设备
            self.reporter.on_status("检测设备...")
            if self._cancel_flag.is_set():
                return
            device = m1.check_device()

            # 同步照片
            if self.mode in ("photo", "all"):
                self._sync_media(device, m2, m3, "照片",
                                 m2.scan_phone_mediastore,
                                 self.photo_dir, m2.PHOTO_EXTENSIONS)

            if self._cancel_flag.is_set():
                return

            # 同步视频
            if self.mode in ("video", "all"):
                self._sync_media(device, m2, m3, "视频",
                                 m2.scan_videos_mediastore,
                                 self.video_dir, m2.VIDEO_EXTENSIONS)

        except Exception as e:
            self.reporter.on_error(str(e))

    def _sync_media(self, device, m2, m3, label, scan_fn, target_dir, extensions) -> None:
        """同步一种媒体类型。"""
        self.reporter.on_status(f"扫描手机{label} (MediaStore)...")
        if self._cancel_flag.is_set():
            return

        phone_files = scan_fn(device)
        if not phone_files:
            self.reporter.on_status(f"未发现{label}")
            return

        self.reporter.on_status(f"比对{label}去重...")
        if self._cancel_flag.is_set():
            return

        pc_index = m2.scan_pc(target_dir, extensions)
        new_files, conflict_files = m2.diff(phone_files, pc_index)

        verify = self._get_verify_conflicts()
        if conflict_files:
            if verify:
                self.reporter.on_status(f"哈希确认 {len(conflict_files)} 个冲突文件...")
            else:
                self.reporter.on_status(f"按文件名+大小判定 {len(conflict_files)} 个冲突为已下载(跳过确认)")
            hash_confirmed = m2.hash_verify(device, conflict_files, reporter=self.reporter, verify=verify)
        else:
            hash_confirmed = []

        download_list = m2.build_download_list(new_files, hash_confirmed)
        download_size = sum(f["size"] for f in download_list)
        self.reporter.on_diff_result(
            len(phone_files), len(download_list), 0,
            download_size / (1024**3)
        )

        if not download_list:
            self.reporter.on_status(f"所有{label}已同步")
            return

        if self._cancel_flag.is_set():
            return

        result = m3.download(device, download_list, target_dir, reporter=self.reporter)
        self.reporter.on_download_complete(
            result["success"], result["failed"], 0
        )
