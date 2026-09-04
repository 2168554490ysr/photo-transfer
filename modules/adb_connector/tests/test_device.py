"""模块 1 测试 — ADB 连接管理

@req REQ-01: USB 设备检测
@req REQ-02: 文件列表获取
@req REQ-03: 单文件下载
@req REQ-04: 设备信息获取
@req REQ-05: 命令超时与重试
"""

import pytest
import subprocess
from unittest.mock import patch, MagicMock

from modules import load_module

device = load_module("adb_connector", "device")
check_device = device.check_device
list_files = device.list_files
pull_file = device.pull_file
get_device_info = device.get_device_info
AdbError = device.AdbError
TIMEOUT = device.TIMEOUT


# @req REQ-01: USB 设备检测
class TestCheckDevice:
    """设备检测测试。"""

    def test_no_device(self):
        """无设备连接时抛出 AdbError。"""
        mock = MagicMock()
        mock.stdout = "List of devices attached\n\n"
        mock.returncode = 0
        with patch("subprocess.run", return_value=mock):
            with pytest.raises(AdbError, match="未检测到USB设备"):
                check_device()

    def test_single_device(self):
        """单设备连接时返回序列号。"""
        mock = MagicMock()
        mock.stdout = "List of devices attached\nABC123\tdevice\n"
        mock.returncode = 0
        with patch("subprocess.run", return_value=mock):
            result = check_device()
            assert result == "ABC123"

    def test_multiple_devices(self):
        """多设备连接时抛出 AdbError。"""
        mock = MagicMock()
        mock.stdout = "List of devices attached\nABC123\tdevice\nDEF456\tdevice\n"
        mock.returncode = 0
        with patch("subprocess.run", return_value=mock):
            with pytest.raises(AdbError, match="多个设备"):
                check_device()

    def test_unauthorized_device(self):
        """未授权设备不计入。"""
        mock = MagicMock()
        mock.stdout = "List of devices attached\nABC123\tunauthorized\n"
        mock.returncode = 0
        with patch("subprocess.run", return_value=mock):
            with pytest.raises(AdbError, match="未检测到USB设备"):
                check_device()


# @req REQ-02: 文件列表获取
class TestListFiles:
    """文件列表获取测试。"""

    def test_empty_directory(self):
        """空目录返回空列表。"""
        mock_find = MagicMock()
        mock_find.stdout = ""
        mock_find.returncode = 0

        mock_check = MagicMock()
        mock_check.stdout = "EXISTS\n"
        mock_check.returncode = 0

        with patch("subprocess.run", side_effect=[mock_check, mock_find]):
            result = list_files("DEVICE", "/sdcard/empty")
            assert result == []

    def test_directory_not_found(self):
        """不存在的目录抛出 AdbError。"""
        mock = MagicMock()
        mock.stdout = "NOT_FOUND\n"
        mock.returncode = 0
        with patch("subprocess.run", return_value=mock):
            with pytest.raises(AdbError, match="路径不存在"):
                list_files("DEVICE", "/sdcard/nope")

    def test_list_files_with_attributes(self):
        """正常文件列表返回正确的结构（xargs 批量 stat）。"""
        mock_check = MagicMock()
        mock_check.stdout = "EXISTS\n"
        mock_check.returncode = 0

        # 新实现：find -print0 | xargs -n 500 stat 一次返回所有文件的 stat 结果
        mock_stat = MagicMock()
        mock_stat.stdout = (
            "/sdcard/DCIM/Camera/IMG_001.jpg|5242880|1750000000\n"
            "/sdcard/DCIM/Camera/IMG_002.jpg|3145728|1750000100\n"
        )
        mock_stat.returncode = 0

        with patch("subprocess.run", side_effect=[mock_check, mock_stat]):
            result = list_files("DEVICE", "/sdcard/DCIM/Camera")
            assert len(result) == 2
            assert result[0]["name"] == "IMG_001.jpg"
            assert result[0]["size"] == 5242880
            assert result[0]["mtime"] == 1750000000


# @req REQ-03: 单文件下载
class TestPullFile:
    """文件下载测试。"""

    def test_pull_success(self, tmp_path):
        """下载成功时返回 True 且文件存在。"""
        local = tmp_path / "subdir" / "test.jpg"

        mock = MagicMock()
        mock.returncode = 0

        with patch("subprocess.run", return_value=mock):
            with patch("os.path.isfile", return_value=True):
                with patch("os.makedirs"):
                    result = pull_file("DEVICE", "/sdcard/test.jpg", str(local))
                    assert result is True

    def test_pull_file_not_found(self, tmp_path):
        """下载后文件不存在返回 False。"""
        local = tmp_path / "test.jpg"

        mock = MagicMock()
        mock.returncode = 0

        with patch("subprocess.run", return_value=mock):
            with patch("os.path.isfile", return_value=False):
                with patch("os.makedirs"):
                    result = pull_file("DEVICE", "/sdcard/test.jpg", str(local))
                    assert result is False


# @req REQ-04: 设备信息获取
class TestGetDeviceInfo:
    """设备信息获取测试。"""

    def test_get_info(self):
        """返回设备型号和 Android 版本。"""
        mock_model = MagicMock()
        mock_model.stdout = "Redmi K60\n"
        mock_model.returncode = 0

        mock_ver = MagicMock()
        mock_ver.stdout = "14\n"
        mock_ver.returncode = 0

        mock_ls = MagicMock()
        mock_ls.stdout = "DCIM\nDownload\nPictures\n"
        mock_ls.returncode = 0

        with patch("subprocess.run", side_effect=[mock_model, mock_ver, mock_ls]):
            info = get_device_info("DEVICE")
            assert info["model"] == "Redmi K60"
            assert info["android_version"] == "14"
            assert "DCIM" in info["storage_roots"]


# @req REQ-05: 命令超时与重试
class TestTimeoutRetry:
    """超时与重试测试。"""

    def test_retry_on_timeout_then_success(self):
        """第一次超时，重试成功。"""
        mock_fail = MagicMock(side_effect=subprocess.TimeoutExpired("adb", 30))
        mock_success = MagicMock()
        mock_success.stdout = "List of devices attached\nABC123\tdevice\n"
        mock_success.returncode = 0

        with patch("subprocess.run", side_effect=[mock_fail, mock_success]):
            result = check_device()
            assert result == "ABC123"

    def test_retry_exhausted(self):
        """两次都超时，抛出 AdbError。"""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("adb", 30)):
            with pytest.raises(AdbError, match="超时"):
                check_device()
