"""模块 3 — 下载调度

@req REQ-01: 磁盘空间预检
@req REQ-02: 批量下载
@req REQ-03: 实时进度显示
@req REQ-04: 断点续传
@req REQ-05: 错误容忍
@req REQ-06: 同步日志

串行下载，实时进度，断点续传，单文件错误不中断。
"""

import os
import json
import time
import shutil
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from typing import Optional
from lib.reporter import ProgressReporter
from modules import load_module as _load_module
_m1_device = _load_module("adb_connector", "device")
pull_file = _m1_device.pull_file

PROGRESS_FILE = ".sync_progress.json"
LOG_FILE = ".sync_log.json"
# 超过此大小的大文件在下载中实时轮询上报进度（避免进度条长时间不动）
LIVE_PULL_THRESHOLD = 8 * 1024 * 1024  # 8MB
# 并发下载线程数（实测 4 已接近吞吐上限）
CONCURRENCY = 4


# @req REQ-01: 磁盘空间预检
def check_disk_space(target_dir: str, total_size: int) -> None:
    """检查目标磁盘剩余空间是否足够。

    Raises:
        OSError: 空间不足
    """
    drive = os.path.splitdrive(target_dir)[0] or "C:"
    usage = shutil.disk_usage(drive)
    free = usage.free
    if free < total_size:
        free_gb = free / (1024**3)
        need_gb = total_size / (1024**3)
        raise OSError(
            f"磁盘空间不足: 需要 {need_gb:.1f} GB, 剩余 {free_gb:.1f} GB"
        )


def _pull_live(device: str, remote_path: str, local_path: str, file_size: int,
               reporter: ProgressReporter, index: int, total: int, filename: str,
               base_bytes: int, total_bytes: int, poll: float = 0.15) -> tuple[bool, str]:
    """后台线程执行 pull，主循环轮询目标文件大小，实时上报字节进度。

    返回 (是否成功, 错误信息)。成功时 local_path 已存在（大小由调用方校验）。
    """
    result = {"ok": False, "error": None}

    def _pull():
        try:
            ok = pull_file(device, remote_path, local_path)
            result["ok"] = ok and os.path.isfile(local_path)
            if not result["ok"]:
                result["error"] = "下载后文件未找到"
        except Exception as e:
            result["error"] = str(e)

    t = threading.Thread(target=_pull, daemon=True)
    t.start()

    last_cur = 0
    last_t = time.time()
    speed = 0.0
    while t.is_alive():
        cur = os.path.getsize(local_path) if os.path.isfile(local_path) else 0
        cur = min(cur, file_size)
        now = time.time()
        dt = now - last_t
        if dt > 0:
            speed = (cur - last_cur) / dt / (1024 ** 2)
        last_cur = cur
        last_t = now
        remain_min = 0
        if speed > 0:
            remain_min = int((file_size - cur) / (speed * 1024 * 1024))
        reporter.on_download_progress(
            index, total, filename, max(speed, 0.0), remain_min,
            min(base_bytes + cur, total_bytes)
        )
        t.join(timeout=poll)
    t.join()
    return result["ok"], result["error"] or ""


# @req REQ-02, REQ-03, REQ-04, REQ-05
def download(device: str, file_list: list[dict], target_root: str,
             reporter: Optional[ProgressReporter] = None) -> dict:
    """批量下载照片文件。

    Args:
        device: 设备序列号
        file_list: 待下载清单
        target_root: PC 目标根目录
        reporter: 可选进度报告器，None 则使用 print()

    Returns:
        {success, failed, errors, start_time, end_time}
    """
    if not file_list:
        return {"success": 0, "failed": 0, "errors": [], "start_time": None, "end_time": None}

    # 预检空间
    total_size = sum(f["size"] for f in file_list)
    check_disk_space(target_root, total_size)

    # 加载进度文件
    progress = _load_progress(file_list)

    # 过滤已完成文件 + 检测不完整文件
    pending = _filter_pending(file_list, progress, target_root)

    if not pending:
        msg = "所有文件已下载，无需同步。"
        if reporter:
            reporter.on_status(msg)
        else:
            print(msg)
        return {
            "success": 0, "failed": 0, "errors": [],
            "start_time": datetime.now().isoformat(),
            "end_time": datetime.now().isoformat(),
        }

    start_time = datetime.now()
    completed_set = set(progress.get("completed", []))
    completed_size = sum(f["size"] for f in file_list if f["name"] in completed_set)
    # 并发共享状态（用锁保护进度文件写入与汇总）
    state_lock = threading.Lock()
    state = {"download": completed_size, "success": 0, "failed": 0, "errors": []}

    if reporter:
        reporter.on_download_start(len(pending), total_size)
    else:
        print(f"待下载: {len(pending)} 个文件, 总大小 {_format_size(total_size)}")
        print(f"已完成: {len(completed_set)}, 跳过\n")

    total = len(pending)

    def work(idx: int, f: dict) -> None:
        """下载单个文件（含实时进度、重试、大小校验），线程池并发执行。"""
        local_subdir = f["local_subdir"]
        local_filename = f["local_filename"]
        local_path = os.path.join(target_root, local_subdir, local_filename)
        phone_path = f["phone_path"]
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        progress_str = f"[{idx}/{total}] {local_subdir}/{local_filename}"

        try:
            file_start = time.time()
            if reporter and f["size"] >= LIVE_PULL_THRESHOLD:
                with state_lock:
                    base = state["download"]
                ok, pull_err = _pull_live(device, phone_path, local_path, f["size"],
                                          reporter, idx, total,
                                          f"{local_subdir}/{local_filename}",
                                          base, total_size)
                file_elapsed = time.time() - file_start
                if not ok:
                    raise Exception(pull_err or "下载失败")
            else:
                success_flag = pull_file(device, phone_path, local_path, f["size"])
                file_elapsed = time.time() - file_start
                if not success_flag:
                    raise Exception("下载后文件未找到")

            # 验证文件完整性
            local_size = os.path.getsize(local_path)
            if local_size != f["size"]:
                os.remove(local_path)
                raise Exception(f"文件大小不匹配: 预期 {f['size']}, 实际 {local_size}")

            with state_lock:
                _update_progress(progress, f)
                state["download"] += f["size"]
                state["success"] += 1
                bytes_done = state["download"]

            speed = f["size"] / file_elapsed / (1024**2) if file_elapsed > 0 else 0
            remain_min = int(_estimate_remaining_minutes(pending[idx:]))
            if reporter:
                reporter.on_download_progress(idx, total, f"{local_subdir}/{local_filename}",
                                              speed, remain_min, bytes_done)
            else:
                print(f"  {progress_str}  OK  {speed:.1f} MB/s  ...")

        except Exception as e:
            # 第一次失败，重试（重试用普通拉取，不再实时轮询）
            try:
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                pull_file(device, phone_path, local_path, f["size"])
                local_size = os.path.getsize(local_path)
                if local_size != f["size"]:
                    os.remove(local_path)
                    raise Exception("重试后文件大小仍不匹配")

                with state_lock:
                    _update_progress(progress, f)
                    state["download"] += f["size"]
                    state["success"] += 1
                msg = f"{local_subdir}/{local_filename} (重试成功)"
                if reporter:
                    reporter.on_status(msg)
                else:
                    print(f"  {progress_str}  OK (retry)")
            except Exception as e2:
                with state_lock:
                    state["failed"] += 1
                    state["errors"].append(f"{local_subdir}/{local_filename}: {e2}")
                if reporter:
                    reporter.on_download_file_error(f"{local_subdir}/{local_filename}", str(e2))
                else:
                    print(f"  {progress_str}  FAIL  {e2}")

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futures = [ex.submit(work, idx, f) for idx, f in enumerate(pending, 1)]
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception:
                pass

    success = state["success"]
    failed = state["failed"]
    errors = state["errors"]

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    # 写入同步日志
    _write_log(file_list, success, failed, errors, duration)

    # 标记进度完成
    progress["status"] = "completed"
    progress["completed_at"] = end_time.isoformat()
    _save_progress(progress)

    # 输出汇总
    if reporter:
        reporter.on_download_complete(success, failed, duration)
    else:
        print(f"\n{'='*50}")
        print(f"同步完成: {success} 成功, {failed} 失败, 耗时 {_format_duration(duration)}")
        if errors:
            print(f"失败文件:")
            for err in errors:
                print(f"  - {err}")

    return {
        "success": success, "failed": failed, "errors": errors,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
    }


# --- 进度文件操作 ---

def _load_progress(file_list: list[dict]) -> dict:
    """加载进度文件。如果状态为 completed 则重置。"""
    try:
        with open(PROGRESS_FILE, "r", encoding="utf-8") as fh:
            p = json.load(fh)
        if p.get("status") == "completed":
            # 上次已完成，重新开始
            return {"status": "in_progress", "completed": []}
        # 确保 completed 是 list
        if "completed" not in p:
            p["completed"] = []
        return p
    except (FileNotFoundError, json.JSONDecodeError):
        return {"status": "in_progress", "completed": []}


def _save_progress(progress: dict) -> None:
    """保存进度到磁盘（确保落盘）。"""
    with open(PROGRESS_FILE, "w", encoding="utf-8") as fh:
        json.dump(progress, fh, ensure_ascii=False)
        fh.flush()
        os.fsync(fh.fileno())


def _update_progress(progress: dict, file_info: dict) -> None:
    """追加一个已完成文件到进度。"""
    key = f"{file_info['local_subdir']}/{file_info['local_filename']}"
    completed = progress.get("completed", [])
    completed.append(key)
    progress["completed"] = completed
    _save_progress(progress)


def _filter_pending(file_list: list[dict], progress: dict, target_root: str) -> list[dict]:
    """过滤：跳过已完成文件，检测并删除不完整文件。"""
    completed = set(progress.get("completed", []))
    pending = []

    for f in file_list:
        key = f"{f['local_subdir']}/{f['local_filename']}"
        if key in completed:
            # 验证已完成文件的完整性
            local_path = os.path.join(target_root, f["local_subdir"], f["local_filename"])
            if os.path.isfile(local_path) and os.path.getsize(local_path) == f["size"]:
                continue  # 完整，跳过
            else:
                # 不完整，从已完成中移除，重新下载
                completed.discard(key)
                progress["completed"] = list(completed)
                _save_progress(progress)
        pending.append(f)

    return pending


# --- 辅助函数 ---

# @req REQ-03: 实时进度显示
def _estimate_remaining(remain_files: list[dict]) -> str:
    """估算剩余时间（字符串格式，用于 CLI）。"""
    if not remain_files:
        return "0 分钟"
    remain_size = sum(f["size"] for f in remain_files)
    seconds = remain_size / (10 * 1024 * 1024)
    return _format_duration(seconds)


def _estimate_remaining_minutes(remain_files: list[dict]) -> int:
    """估算剩余分钟数（整数，用于 reporter）。"""
    if not remain_files:
        return 0
    remain_size = sum(f["size"] for f in remain_files)
    seconds = remain_size / (10 * 1024 * 1024)
    return max(1, int(seconds / 60))
    """估算剩余时间（基于 10 MB/s 保守速度）。"""
    if not remain_files:
        return "0 分钟"
    remain_size = sum(f["size"] for f in remain_files)
    # 假设 10 MB/s 传输速度
    seconds = remain_size / (10 * 1024 * 1024)
    return _format_duration(seconds)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024**2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024**3:
        return f"{size_bytes / (1024**2):.1f} MB"
    else:
        return f"{size_bytes / (1024**3):.1f} GB"


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f} 秒"
    else:
        return f"{seconds / 60:.0f} 分钟"


# @req REQ-06: 同步日志
def _write_log(file_list: list[dict], success: int, failed: int, errors: list[str], duration: float) -> None:
    """追加本次同步记录到日志文件。"""
    # 读取已有日志
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as fh:
            logs = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        logs = []

    logs.append({
        "date": datetime.now().isoformat(),
        "total_phone_files": len(file_list),
        "new_downloaded": success,
        "failed_count": failed,
        "failed_list": errors,
        "duration_seconds": round(duration, 1),
    })

    with open(LOG_FILE, "w", encoding="utf-8") as fh:
        json.dump(logs, fh, ensure_ascii=False, indent=2)
