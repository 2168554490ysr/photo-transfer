"""模块 3 测试 — 下载调度

@req REQ-01: 磁盘空间预检
@req REQ-02: 批量下载
@req REQ-03: 实时进度显示
@req REQ-04: 断点续传
@req REQ-05: 错误容忍
@req REQ-06: 同步日志
"""

import os
import json
import pytest
from unittest.mock import patch, MagicMock

from modules import load_module

downloader = load_module("photo_downloader", "downloader")
check_disk_space = downloader.check_disk_space
download = downloader.download
_load_progress = downloader._load_progress
_save_progress = downloader._save_progress
_update_progress = downloader._update_progress
_filter_pending = downloader._filter_pending
PROGRESS_FILE = downloader.PROGRESS_FILE
LOG_FILE = downloader.LOG_FILE


# @req REQ-01: 磁盘空间预检
class TestCheckDiskSpace:
    """磁盘空间预检测试。"""

    def test_space_sufficient(self):
        """空间足够时正常通过（10 GB 剩余 vs 1 GB 需求）。"""
        check_disk_space("C:/", 1 * 1024**3)

    def test_space_insufficient(self):
        """空间不足时抛出 OSError。"""
        with pytest.raises(OSError, match="磁盘空间不足"):
            check_disk_space("C:/", 10 * 1024**9)  # 10 TB 需求肯定不够


# @req REQ-04: 断点续传
class TestProgressFile:
    """进度文件读写测试。"""

    def test_load_new(self, tmp_path, monkeypatch):
        """无进度文件时返回初始状态。"""
        monkeypatch.setattr(downloader, "PROGRESS_FILE", str(tmp_path / ".sync_progress.json"))
        progress = _load_progress([])
        assert progress["status"] == "in_progress"
        assert progress["completed"] == []

    def test_load_completed_resets(self, tmp_path, monkeypatch):
        """上次已完成则重置进度。"""
        pfile = tmp_path / ".sync_progress.json"
        pfile.write_text(json.dumps({"status": "completed", "completed": ["a/b.jpg"]}))
        monkeypatch.setattr(downloader, "PROGRESS_FILE", str(pfile))
        progress = _load_progress([])
        assert progress["status"] == "in_progress"
        assert progress["completed"] == []

    def test_load_in_progress_keeps(self, tmp_path, monkeypatch):
        """未完成的进度保留已完成列表。"""
        pfile = tmp_path / ".sync_progress.json"
        pfile.write_text(json.dumps({"status": "in_progress", "completed": ["a/b.jpg"]}))
        monkeypatch.setattr(downloader, "PROGRESS_FILE", str(pfile))
        progress = _load_progress([])
        assert progress["completed"] == ["a/b.jpg"]

    def test_save_and_update(self, tmp_path, monkeypatch):
        """保存后再加载数据一致。"""
        pfile = tmp_path / ".sync_progress.json"
        monkeypatch.setattr(downloader, "PROGRESS_FILE", str(pfile))
        progress = {"status": "in_progress", "completed": []}
        _update_progress(progress, {"local_subdir": "2026-07-12", "local_filename": "IMG_001.jpg"})
        loaded = _load_progress([])
        assert "2026-07-12/IMG_001.jpg" in loaded["completed"]


# @req REQ-04: 断点续传 — 过滤逻辑
class TestFilterPending:
    """待下载过滤测试（跳过已完成 / 重下不完整文件）。"""

    def test_skip_completed_intact(self, tmp_path):
        """完整文件被跳过。"""
        subdir = tmp_path / "2026-07-12"
        subdir.mkdir(parents=True)
        f = subdir / "IMG_001.jpg"
        f.write_bytes(b"x" * 100)

        file_list = [
            {"name": "IMG_001.jpg", "size": 100, "local_subdir": "2026-07-12", "local_filename": "IMG_001.jpg"},
        ]
        progress = {"status": "in_progress", "completed": ["2026-07-12/IMG_001.jpg"]}
        pending = _filter_pending(file_list, progress, str(tmp_path))
        assert len(pending) == 0

    def test_redownload_incomplete_size(self, tmp_path):
        """不完整文件（大小不匹配）重新加入下载队列。"""
        subdir = tmp_path / "2026-07-12"
        subdir.mkdir(parents=True)
        f = subdir / "IMG_001.jpg"
        f.write_bytes(b"x" * 50)  # 大小不匹配

        file_list = [
            {"name": "IMG_001.jpg", "size": 100, "local_subdir": "2026-07-12", "local_filename": "IMG_001.jpg"},
        ]
        progress = {"status": "in_progress", "completed": ["2026-07-12/IMG_001.jpg"]}
        pending = _filter_pending(file_list, progress, str(tmp_path))
        assert len(pending) == 1

    def test_redownload_missing_file(self, tmp_path):
        """文件不存在重新加入队列。"""
        file_list = [
            {"name": "IMG_001.jpg", "size": 100, "local_subdir": "2026-07-12", "local_filename": "IMG_001.jpg"},
        ]
        progress = {"status": "in_progress", "completed": ["2026-07-12/IMG_001.jpg"]}
        pending = _filter_pending(file_list, progress, str(tmp_path))
        assert len(pending) == 1


# @req REQ-02, REQ-05: 下载流程
class TestDownload:
    """下载流程测试。"""

    def test_empty_list(self, tmp_path):
        """空待下载列表返回零结果。"""
        result = download("DEVICE", [], str(tmp_path))
        assert result["success"] == 0
        assert result["failed"] == 0

    def test_download_with_mock(self, tmp_path, monkeypatch):
        """模拟单文件下载成功。"""
        subdir = tmp_path / "2026-07-12"
        subdir.mkdir(parents=True)

        file_list = [
            {"name": "IMG_001.jpg", "size": 100, "mtime": 1750000000,
             "phone_path": "/sdcard/IMG_001.jpg",
             "local_subdir": "2026-07-12", "local_filename": "IMG_001.jpg"},
        ]

        # 使用临时进度文件和日志文件避免污染工作目录
        monkeypatch.setattr(downloader, "PROGRESS_FILE", str(tmp_path / ".sync_progress.json"))
        monkeypatch.setattr(downloader, "LOG_FILE", str(tmp_path / ".sync_log.json"))

        with patch.object(downloader, "pull_file", return_value=True):
            with patch.object(downloader, "check_disk_space"):
                with patch("os.path.getsize", return_value=100):
                    result = download("DEVICE", file_list, str(tmp_path))
                    assert result["success"] == 1
                    assert result["failed"] == 0

    def test_download_reports_bytes(self, tmp_path, monkeypatch):
        """有 reporter 时，进度上报携带累计已下载字节。"""
        subdir = tmp_path / "2026-07-12"
        subdir.mkdir(parents=True)
        file_list = [
            {"name": "IMG_001.jpg", "size": 100, "mtime": 1750000000,
             "phone_path": "/sdcard/IMG_001.jpg",
             "local_subdir": "2026-07-12", "local_filename": "IMG_001.jpg"},
        ]
        monkeypatch.setattr(downloader, "PROGRESS_FILE", str(tmp_path / ".sync_progress.json"))
        monkeypatch.setattr(downloader, "LOG_FILE", str(tmp_path / ".sync_log.json"))
        rep = MagicMock()
        with patch.object(downloader, "pull_file", return_value=True):
            with patch.object(downloader, "check_disk_space"):
                with patch("os.path.getsize", return_value=100):
                    download("DEVICE", file_list, str(tmp_path), reporter=rep)
        assert rep.on_download_start.called
        assert rep.on_download_progress.called
        # 最后一个参数是 downloaded_bytes
        assert rep.on_download_progress.call_args[0][-1] == 100
