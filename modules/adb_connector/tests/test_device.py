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


def _popen(stdout: str = "", stderr: str = "", returncode: int = 0) -> MagicMock:
    """构造一个模拟 subprocess.Popen 返回对象：communicate() 返回 (stdout, stderr)。"""
    p = MagicMock()
    p.communicate.return_value = (stdout, stderr)
    p.returncode = returncode
    return p


# @req REQ-01: USB 设备检测
class TestCheckDevice:
    """设备检测测试。"""

    def test_no_device(self):
        """无设备连接时抛出 AdbError。"""
        with patch("subprocess.Popen", return_value=_popen(stdout="List of devices attached\n\n")):
            with pytest.raises(AdbError, match="未检测到USB设备"):
                check_device()

    def test_single_device(self):
        """单设备连接时返回序列号。"""
        with patch("subprocess.Popen",
                   return_value=_popen(stdout="List of devices attached\nABC123\tdevice\n")):
            result = check_device()
            assert result == "ABC123"

    def test_multiple_devices(self):
        """多设备连接时抛出 AdbError。"""
        with patch("subprocess.Popen",
                   return_value=_popen(stdout="List of devices attached\nABC123\tdevice\nDEF456\tdevice\n")):
            with pytest.raises(AdbError, match="多个设备"):
                check_device()

    def test_unauthorized_device(self):
        """未授权设备不计入。"""
        with patch("subprocess.Popen",
                   return_value=_popen(stdout="List of devices attached\nABC123\tunauthorized\n")):
            with pytest.raises(AdbError, match="未检测到USB设备"):
                check_device()


# @req REQ-02: 文件列表获取
class TestListFiles:
    """文件列表获取测试。"""

    def test_empty_directory(self):
        """空目录返回空列表。"""
        with patch("subprocess.Popen",
                   side_effect=[_popen(stdout="EXISTS\n"), _popen(stdout="")]):
            result = list_files("DEVICE", "/sdcard/empty")
            assert result == []

    def test_directory_not_found(self):
        """不存在的目录抛出 AdbError。"""
        with patch("subprocess.Popen", return_value=_popen(stdout="NOT_FOUND\n")):
            with pytest.raises(AdbError, match="路径不存在"):
                list_files("DEVICE", "/sdcard/nope")

    def test_list_files_with_attributes(self):
        """正常文件列表返回正确的结构（xargs 批量 stat）。"""
        stat_out = (
            "/sdcard/DCIM/Camera/IMG_001.jpg|5242880|1750000000\n"
            "/sdcard/DCIM/Camera/IMG_002.jpg|3145728|1750000100\n"
        )
        with patch("subprocess.Popen",
                   side_effect=[_popen(stdout="EXISTS\n"), _popen(stdout=stat_out)]):
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
        with patch("subprocess.Popen", return_value=_popen()):
            with patch("os.path.isfile", return_value=True):
                with patch("os.makedirs"):
                    result = pull_file("DEVICE", "/sdcard/test.jpg", str(local))
                    assert result is True

    def test_pull_file_not_found(self, tmp_path):
        """下载后文件不存在返回 False。"""
        local = tmp_path / "test.jpg"
        with patch("subprocess.Popen", return_value=_popen()):
            with patch("os.path.isfile", return_value=False):
                with patch("os.makedirs"):
                    result = pull_file("DEVICE", "/sdcard/test.jpg", str(local))
                    assert result is False


# @req REQ-04: 设备信息获取
class TestGetDeviceInfo:
    """设备信息获取测试。"""

    def test_get_info(self):
        """返回设备型号和 Android 版本。"""
        with patch("subprocess.Popen", side_effect=[
            _popen(stdout="Redmi K60\n"),
            _popen(stdout="14\n"),
            _popen(stdout="DCIM\nDownload\nPictures\n"),
        ]):
            info = get_device_info("DEVICE")
            assert info["model"] == "Redmi K60"
            assert info["android_version"] == "14"
            assert "DCIM" in info["storage_roots"]


# @req REQ-05: 命令超时与重试
class TestTimeoutRetry:
    """超时与重试测试。"""

    def test_retry_on_timeout_then_success(self):
        """第一次超时，重试成功。"""
        p1 = _popen()
        p1.communicate.side_effect = [subprocess.TimeoutExpired("adb", 30), ("", "")]
        p2 = _popen(stdout="List of devices attached\nABC123\tdevice\n", returncode=0)
        with patch("subprocess.Popen", side_effect=[p1, p2]):
            result = check_device()
            assert result == "ABC123"

    def test_retry_exhausted(self):
        """两次都超时，抛出 AdbError。"""
        p1 = _popen()
        p1.communicate.side_effect = [subprocess.TimeoutExpired("adb", 30), ("", "")]
        p2 = _popen()
        p2.communicate.side_effect = [subprocess.TimeoutExpired("adb", 30), ("", "")]
        with patch("subprocess.Popen", side_effect=[p1, p2]):
            with pytest.raises(AdbError, match="超时"):
                check_device()


# @req REQ-05: 命令无窗口运行（GUI/pythonw 下避免 adb 弹黑框）
class TestNoWindowSubprocess:
    """子进程无窗口运行测试。"""

    def test_adb_runs_with_no_window(self):
        """subprocess.Popen 应携带 creationflags（Windows CREATE_NO_WINDOW）。"""
        expected = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with patch("subprocess.Popen",
                   return_value=_popen(stdout="List of devices attached\nABC123\tdevice\n")) as m:
            check_device()
            m.assert_called_once()
            assert m.call_args.kwargs.get("creationflags") == expected


# @req REQ-05: 取消时不再重试
class TestCancel:
    """取消语义测试。"""

    def test_cancelled_does_not_retry(self):
        """置取消标志后，失败命令不再重试（只 spawn 一次）并抛"已取消"。"""
        device._cancelled.set()
        try:
            p = _popen(stdout="", returncode=1)
            with patch("subprocess.Popen", return_value=p) as m:
                with pytest.raises(AdbError, match="已取消"):
                    check_device()
                assert m.call_count == 1  # 不因失败重试
        finally:
            device._cancelled.clear()

    def test_reset_clears_cancel(self):
        """reset_cancel 后取消标志清除。"""
        device._cancelled.set()
        device.reset_cancel()
        assert device._cancelled.is_set() is False
