"""模块 2 测试 — 照片扫描与去重

@req REQ-01: 手机照片扫描
@req REQ-02: PC 文件索引
@req REQ-03: 去重比对
@req REQ-04: 哈希确认
@req REQ-05: 待下载清单输出
"""

import os
import json
from unittest.mock import patch

from modules import load_module

scanner = load_module("photo_scanner", "scanner")
scan_phone = scanner.scan_phone
scan_pc = scanner.scan_pc
diff = scanner.diff
hash_verify = scanner.hash_verify
build_download_list = scanner.build_download_list
_is_photo = scanner._is_photo


# @req REQ-01: 手机照片扫描
class TestScanPhone:
    """手机扫描测试。"""

    def test_filters_photos_only(self):
        """仅返回照片扩展名的文件。"""
        mock_files = [
            {"name": "IMG_001.jpg", "size": 100, "mtime": 1000, "path": "/sdcard/DCIM/Camera/IMG_001.jpg"},
            {"name": "notes.txt", "size": 50, "mtime": 1000, "path": "/sdcard/DCIM/Camera/notes.txt"},
            {"name": "IMG_002.PNG", "size": 200, "mtime": 1000, "path": "/sdcard/DCIM/Camera/IMG_002.PNG"},
            {"name": "thumb.db", "size": 10, "mtime": 1000, "path": "/sdcard/DCIM/Camera/thumb.db"},
        ]
        # scan_phone 内部调 _m1_device.list_files，mock 已加载模块的属性
        with patch.object(scanner._m1_device, "list_files", return_value=mock_files):
            result = scan_phone("DEVICE", ["/sdcard/DCIM/Camera"])
            assert len(result) == 2
            names = {f["name"] for f in result}
            assert "IMG_001.jpg" in names
            assert "IMG_002.PNG" in names


# @req REQ-02: PC 文件索引
class TestScanPc:
    """PC 扫描测试。"""

    def test_empty_dir(self, tmp_path):
        """空目录返回空索引。"""
        index = scan_pc(str(tmp_path))
        assert index == {}

    def test_index_photos(self, tmp_path):
        """照片文件正确索引。"""
        (tmp_path / "2026-07-12").mkdir(parents=True)
        f1 = tmp_path / "2026-07-12" / "IMG_001.jpg"
        f1.write_bytes(b"x" * 100)
        f2 = tmp_path / "2026-07-12" / "IMG_002.jpg"
        f2.write_bytes(b"y" * 200)

        index = scan_pc(str(tmp_path))
        assert ("IMG_001.jpg", 100) in index
        assert ("IMG_002.jpg", 200) in index

    def test_ignores_non_photos(self, tmp_path):
        """非照片文件不被索引。"""
        (tmp_path / "test.txt").write_text("hello")
        (tmp_path / "data.json").write_text("{}")
        index = scan_pc(str(tmp_path))
        assert len(index) == 0

    def test_creates_dir_if_missing(self, tmp_path):
        """目标目录不存在时自动创建。"""
        missing = str(tmp_path / "missing_dir")
        index = scan_pc(missing)
        assert os.path.isdir(missing)
        assert index == {}


# @req REQ-03: 去重比对
class TestDiff:
    """去重比对测试。"""

    def test_all_new(self):
        """所有文件都不在 PC 索引中。"""
        phone_files = [
            {"name": "IMG_001.jpg", "size": 100, "mtime": 1000, "path": "/sdcard/IMG_001.jpg"},
            {"name": "IMG_002.jpg", "size": 200, "mtime": 1000, "path": "/sdcard/IMG_002.jpg"},
        ]
        pc_index = {}
        new_files, conflict_files = diff(phone_files, pc_index)
        assert len(new_files) == 2
        assert len(conflict_files) == 0

    def test_some_conflict(self):
        """部分文件在 PC 中已存在（同名同大小）。"""
        phone_files = [
            {"name": "IMG_001.jpg", "size": 100, "mtime": 1000, "path": "/sdcard/IMG_001.jpg"},
            {"name": "IMG_002.jpg", "size": 200, "mtime": 1000, "path": "/sdcard/IMG_002.jpg"},
        ]
        pc_index = {("IMG_001.jpg", 100): "D:/Photos/2026-07-12/IMG_001.jpg"}
        new_files, conflict_files = diff(phone_files, pc_index)
        assert len(new_files) == 1
        assert new_files[0]["name"] == "IMG_002.jpg"
        assert len(conflict_files) == 1
        assert conflict_files[0]["name"] == "IMG_001.jpg"
        assert "pc_path" in conflict_files[0]

    def test_same_name_diff_size(self):
        """同名不同大小视为新文件（不是冲突）。"""
        phone_files = [
            {"name": "IMG_001.jpg", "size": 100, "mtime": 1000, "path": "/sdcard/IMG_001.jpg"},
        ]
        pc_index = {("IMG_001.jpg", 200): "D:/Photos/IMG_001.jpg"}
        new_files, conflict_files = diff(phone_files, pc_index)
        assert len(new_files) == 1
        assert len(conflict_files) == 0


# @req REQ-04: 哈希确认
class TestHashVerify:
    """哈希确认测试。"""

    def test_empty_conflicts(self):
        """空冲突列表返回空。"""
        result = hash_verify("DEVICE", [])
        assert result == []

    def test_verify_false_skips_all(self, tmp_path):
        """默认策略(verify=False)：冲突一律视为重复跳过，不触发哈希/PC读取。"""
        pc = tmp_path / "IMG_001.jpg"
        pc.write_bytes(b"x" * (150 * 1024))
        conflicts = [self._conflict(pc, pc.stat().st_size)]
        with patch.object(scanner, "_phone_file_hash") as mock_phone:
            with patch.object(scanner, "_pc_file_hash") as mock_pchash:
                result = hash_verify("DEVICE", conflicts, verify=False)
        mock_phone.assert_not_called()
        mock_pchash.assert_not_called()
        assert result == []

    def _conflict(self, pc_path, size):
        return {"name": os.path.basename(pc_path), "size": size, "mtime": 1000,
                "path": "/sdcard/" + os.path.basename(pc_path), "pc_path": str(pc_path)}

    def test_confirmed_duplicate_skips_phone_hash(self, tmp_path):
        """缓存中已确认重复的文件跳过手机端哈希，直接判为重复。"""
        pc = tmp_path / "IMG_001.jpg"
        pc.write_bytes(b"x" * (150 * 1024))  # >128KB
        conflicts = [self._conflict(pc, pc.stat().st_size)]
        cache = {("IMG_001.jpg", pc.stat().st_size): {"pc_hash": "AAA", "confirmed": True}}
        with patch.object(scanner, "_load_hash_cache", return_value=cache):
            with patch.object(scanner, "_phone_file_hash") as mock_phone:
                result = hash_verify("DEVICE", conflicts)
        mock_phone.assert_not_called()
        assert result == []

    def test_match_marks_confirmed_and_skips(self, tmp_path):
        """哈希一致：判定为重复、记录缓存 confirmed=True。"""
        pc = tmp_path / "IMG_001.jpg"
        pc.write_bytes(b"x" * (150 * 1024))
        conflicts = [self._conflict(pc, pc.stat().st_size)]
        saved = {}
        with patch.object(scanner, "_load_hash_cache", return_value={}):
            with patch.object(scanner, "_pc_file_hash", return_value="PCHASH"):
                with patch.object(scanner, "_phone_file_hash", return_value="PCHASH"):
                    with patch.object(scanner, "_save_hash_cache",
                                      side_effect=lambda c: saved.update(c)):
                        result = hash_verify("DEVICE", conflicts)
        assert result == []
        assert saved[("IMG_001.jpg", pc.stat().st_size)]["confirmed"] is True

    def test_mismatch_adds_suffix(self, tmp_path):
        """哈希不一致：加入下载清单，文件名加 _1 后缀。"""
        pc = tmp_path / "IMG_001.jpg"
        pc.write_bytes(b"x" * (150 * 1024))
        conflicts = [self._conflict(pc, pc.stat().st_size)]
        with patch.object(scanner, "_load_hash_cache", return_value={}):
            with patch.object(scanner, "_pc_file_hash", return_value="PCHASH"):
                with patch.object(scanner, "_phone_file_hash", return_value="PHONEHASH"):
                    with patch.object(scanner, "_save_hash_cache"):
                        result = hash_verify("DEVICE", conflicts)
        assert len(result) == 1
        assert result[0]["name"] == "IMG_001_1.jpg"
        assert result[0]["size"] == pc.stat().st_size

    def test_phone_hash_failure_adds_as_is(self, tmp_path):
        """手机端哈希计算失败：按不匹配处理，保持原文件名。"""
        pc = tmp_path / "IMG_001.jpg"
        pc.write_bytes(b"x" * (150 * 1024))
        conflicts = [self._conflict(pc, pc.stat().st_size)]
        with patch.object(scanner, "_load_hash_cache", return_value={}):
            with patch.object(scanner, "_pc_file_hash", return_value="PCHASH"):
                with patch.object(scanner, "_phone_file_hash", return_value=None):
                    with patch.object(scanner, "_save_hash_cache"):
                        result = hash_verify("DEVICE", conflicts)
        assert len(result) == 1
        assert result[0]["name"] == "IMG_001.jpg"

    def test_large_file_skips_hash(self, tmp_path):
        """大文件（>100MB）跳过手机端哈希，直接加入下载清单。"""
        pc = tmp_path / "IMG_001.jpg"
        # 不真的写 100MB，直接给大 size
        conflicts = [self._conflict(pc, 101 * 1024 * 1024)]
        with patch.object(scanner, "_load_hash_cache", return_value={}):
            with patch.object(scanner, "_pc_file_hash") as mock_pchash:
                with patch.object(scanner, "_phone_file_hash") as mock_phone:
                    with patch.object(scanner, "_save_hash_cache"):
                        result = hash_verify("DEVICE", conflicts)
        mock_phone.assert_not_called()
        mock_pchash.assert_not_called()
        assert len(result) == 1

    def test_reports_progress(self, tmp_path):
        """传入 reporter 时，哈希确认过程上报进度。"""
        pc = tmp_path / "IMG_001.jpg"
        pc.write_bytes(b"x" * (150 * 1024))
        conflicts = [self._conflict(pc, pc.stat().st_size)]
        class FakeReporter:
            def __init__(self):
                self.messages = []
            def on_status(self, msg):
                self.messages.append(msg)
        rep = FakeReporter()
        with patch.object(scanner, "_load_hash_cache", return_value={}):
            with patch.object(scanner, "_pc_file_hash", return_value="PCHASH"):
                with patch.object(scanner, "_phone_file_hash", return_value="PCHASH"):
                    with patch.object(scanner, "_save_hash_cache"):
                        hash_verify("DEVICE", conflicts, reporter=rep)
        assert any("哈希确认" in m for m in rep.messages)


class TestHashCache:
    """PC 哈希缓存读写与迁移测试。"""

    def test_load_migrates_old_string_format(self, tmp_path, monkeypatch):
        """旧格式（值为 hash 字符串）自动迁移为 pc_hash + confirmed=False。"""
        monkeypatch.setattr(scanner, "HASH_CACHE_FILE", str(tmp_path / "cache.json"))
        (tmp_path / "cache.json").write_text(
            '{"IMG_001.jpg||100": "abc123"}', encoding="utf-8")
        cache = scanner._load_hash_cache()
        assert cache[("IMG_001.jpg", 100)] == {"pc_hash": "abc123", "confirmed": False}

    def test_roundtrip_with_confirmed(self, tmp_path, monkeypatch):
        """dict 格式（含 confirmed）能正确序列化/反序列化。"""
        monkeypatch.setattr(scanner, "HASH_CACHE_FILE", str(tmp_path / "cache.json"))
        cache = {("IMG_001.jpg", 100): {"pc_hash": "abc123", "confirmed": True}}
        scanner._save_hash_cache(cache)
        assert scanner._load_hash_cache()[("IMG_001.jpg", 100)] == \
            {"pc_hash": "abc123", "confirmed": True}


# @req REQ-05: 待下载清单输出
class TestBuildDownloadList:
    """下载清单构建测试。"""

    def test_build_list_with_dates(self):
        """文件正确分配到日期子目录。"""
        new_files = [
            {"name": "IMG_001.jpg", "size": 100, "mtime": 1750000000, "path": "/sdcard/IMG_001.jpg"},
        ]
        result = build_download_list(new_files, [])
        assert len(result) == 1
        assert result[0]["local_filename"] == "IMG_001.jpg"
        assert len(result[0]["local_subdir"]) == 10  # YYYY-MM-DD

    def test_sorted_by_date_then_name(self):
        """结果按日期+文件名排序。"""
        new_files = [
            {"name": "B.jpg", "size": 100, "mtime": 1750000100, "path": "/sdcard/B.jpg"},
            {"name": "A.jpg", "size": 100, "mtime": 1750000000, "path": "/sdcard/A.jpg"},
        ]
        result = build_download_list(new_files, [])
        assert result[0]["name"] == "A.jpg"
        assert result[1]["name"] == "B.jpg"


class TestIsPhoto:
    """扩展名过滤测试。"""

    def test_valid_extensions(self):
        assert _is_photo("IMG_001.jpg") is True
        assert _is_photo("IMG_001.JPEG") is True
        assert _is_photo("IMG_001.png") is True
        assert _is_photo("IMG_001.heic") is True
        assert _is_photo("IMG_001.webp") is True

    def test_invalid_extensions(self):
        assert _is_photo("video.mp4") is False
        assert _is_photo("video.mov") is False
        assert _is_photo("notes.txt") is False
