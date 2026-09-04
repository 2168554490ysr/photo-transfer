"""模块 1 — ADB 连接管理

@req REQ-01: USB 设备检测
@req REQ-02: 文件列表获取
@req REQ-03: 单文件下载
@req REQ-04: 设备信息获取
@req REQ-05: 命令超时与重试

仅支持 USB 有线连接。
"""

import subprocess
import shlex
import os
import time
from typing import Optional

# 全局超时设置（秒）
TIMEOUT = 30
MAX_RETRIES = 1


class AdbError(Exception):
    """ADB 操作异常。"""


def _run(full_cmd: list[str], cmd_desc: str, timeout: int = TIMEOUT) -> str:
    """执行命令行（带超时和重试）。

    Args:
        full_cmd: 完整命令行（如 ['adb', '-s', device, 'shell', ...]）
        cmd_desc: 用于错误提示的命令描述
        timeout: 超时秒数，默认 30s

    Returns:
        命令的标准输出

    Raises:
        AdbError: 命令执行失败（含重试后）
    """
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            if result.returncode != 0:
                last_error = AdbError(
                    f"ADB命令失败: {cmd_desc}\n{result.stderr.strip()}"
                )
                if attempt < MAX_RETRIES:
                    continue
                raise last_error
            if result.stdout is None:
                return ""
            return result.stdout
        except subprocess.TimeoutExpired:
            last_error = AdbError(
                f"ADB命令超时({timeout}s): {cmd_desc}"
            )
            if attempt < MAX_RETRIES:
                continue
            raise last_error

    # 理论上不会到这里，但保留安全出口
    raise last_error  # type: ignore[misc]


def _adb(cmd: str, device: Optional[str] = None, timeout: int = TIMEOUT) -> str:
    """执行 ADB 命令（带超时和重试）。

    Args:
        cmd: ADB 命令（不含 adb 前缀，如 'devices'）
        device: 目标设备序列号，None 表示不指定设备
        timeout: 超时秒数，默认 30s

    Returns:
        命令的标准输出

    Raises:
        AdbError: 命令执行失败（含重试后）
    """
    prefix = ["adb"]
    if device:
        prefix += ["-s", device]
    full_cmd = prefix + shlex.split(cmd)
    return _run(full_cmd, " ".join(full_cmd), timeout)


def adb_shell(device: str, script: str, timeout: int = TIMEOUT) -> str:
    """执行一条 shell 脚本，作为单个 argv 传给 adb，避免 shlex 拆分/引号问题。

    adb shell 会把后续参数用空格拼接后交给设备端 shell 解析，因此复杂脚本
    必须整体作为一个参数传入，不能用 shlex.split（会破坏 `;`、`if`、`$()` 等）。

    Args:
        device: 设备序列号
        script: 完整 shell 脚本（单行，多条命令用 `;` 或 `if` 组合）
        timeout: 超时秒数，默认 30s

    Returns:
        命令的标准输出

    Raises:
        AdbError: 命令执行失败（含重试后）
    """
    full_cmd = ["adb", "-s", device, "shell", script]
    return _run(full_cmd, "adb -s {0} shell <script>".format(device), timeout)


# @req REQ-01: USB 设备检测
def check_device() -> str:
    """检测 USB 连接的 Android 设备。

    Returns:
        设备序列号

    Raises:
        AdbError: 无设备或多设备
    """
    output = _adb("devices")
    lines = output.strip().split("\n")[1:]  # 跳过首行 "List of devices attached"
    devices = []
    for line in lines:
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])

    if len(devices) == 0:
        raise AdbError("未检测到USB设备，请检查数据线连接和USB调试开关")
    if len(devices) > 1:
        raise AdbError(f"检测到多个设备({len(devices)}个)，请只保留一台设备连接")
    return devices[0]


# @req REQ-02: 文件列表获取
def list_files(device: str, remote_path: str) -> list[dict]:
    """递归获取目录下所有文件信息。

    Args:
        device: 设备序列号
        remote_path: 手机端目录路径

    Returns:
        [{name, size, mtime, path}, ...] 按路径排序
    """
    # 检查路径是否存在
    output = _adb(f'shell "test -d {remote_path} && echo EXISTS || echo NOT_FOUND"', device)
    if "NOT_FOUND" in output:
        raise AdbError(f"路径不存在: {remote_path}")

    # 使用 xargs 批量 stat，避免每个文件 fork 一次 stat 进程
    # find 输出文件列表 → xargs 分批传给 stat（每批最多 500 个文件）
    stat_cmd = (
        f'shell "find {remote_path} -type f -print0 2>/dev/null | '
        f'xargs -0 -n 500 stat -c \'%n|%s|%Y\' 2>/dev/null"'
    )
    output = _adb(stat_cmd, device)

    if not output.strip():
        return []

    files = []
    for line in output.strip().split("\n"):
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|", 2)
        if len(parts) == 3:
            full_path = parts[0]
            name = full_path.split("/")[-1]
            try:
                size = int(parts[1])
                mtime = int(parts[2])
            except ValueError:
                continue
            files.append({
                "name": name,
                "size": size,
                "mtime": mtime,
                "path": full_path,
            })

    files.sort(key=lambda f: f["path"])
    return files


# @req REQ-03: 单文件下载
def pull_file(device: str, remote_path: str, local_path: str,
              file_size: Optional[int] = None) -> bool:
    """从手机下载单个文件到 PC。

    Args:
        device: 设备序列号
        remote_path: 手机端文件完整路径
        local_path: PC 端目标路径（含文件名）
        file_size: 已知的文件大小（字节），用于计算超时；None 则额外执行一次 stat

    Returns:
        True 表示下载成功

    Notes:
        file_size 已知时跳过 stat 往返（实测每文件 ~84ms），用于批量下载显著提速。
    """
    # 确保 PC 目标目录存在
    local_dir = os.path.dirname(local_path)
    os.makedirs(local_dir, exist_ok=True)

    # pull 超时按文件大小动态计算: 假设最低 3MB/s, 最少 60s, 最多 3600s
    if file_size is None:
        try:
            size_out = _adb(f'shell "stat -c %s \'{remote_path}\'"', device)
            file_size = int(size_out.strip())
        except Exception:
            file_size = None
    if file_size is not None:
        pull_timeout = max(60, min(3600, file_size // (3 * 1024 * 1024) + 30))
    else:
        pull_timeout = 3600  # 兜底: 1小时

    _adb(f'pull "{remote_path}" "{local_path}"', device, timeout=pull_timeout)
    return os.path.isfile(local_path)


# @req REQ-04: 设备信息获取
def get_device_info(device: str) -> dict:
    """获取设备基本信息。

    Returns:
        {model, android_version, storage_roots}
    """
    model = _adb("shell getprop ro.product.model", device).strip()
    android_ver = _adb("shell getprop ro.build.version.release", device).strip()

    # 列出 /sdcard/ 下的一级目录，辅助用户配置扫描路径
    ls_out = _adb("shell ls /sdcard/", device).strip()
    storage_roots = [d for d in ls_out.split("\n") if d and not d.startswith(".")]

    return {
        "model": model,
        "android_version": android_ver,
        "storage_roots": storage_roots,
    }
