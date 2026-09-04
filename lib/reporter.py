"""进度报告协议。

GUI 和 CLI 通过此协议与后端模块解耦。
后端模块只依赖此协议，不依赖具体 UI 实现。
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class ProgressReporter(Protocol):
    """进度报告协议——GUI 和 CLI 各自实现此接口。"""

    def on_scan_start(self, total_dirs: int) -> None: ...
    def on_scan_progress(self, current_dir: str, files_found: int) -> None: ...

    def on_diff_result(self, total_phone: int, new_count: int, conflict_count: int,
                       download_size_gb: float) -> None: ...

    def on_download_start(self, total_files: int, total_bytes: int) -> None: ...
    def on_download_progress(self, index: int, total: int, filename: str,
                             speed_mbps: float, remaining_minutes: int,
                             downloaded_bytes: int) -> None: ...
    def on_download_file_error(self, filename: str, error: str) -> None: ...
    def on_download_complete(self, success: int, failed: int, duration_secs: float) -> None: ...

    def on_status(self, message: str) -> None: ...
    def on_error(self, message: str) -> None: ...


class ConsoleReporter:
    """CLI 文本输出实现——替代原有 print()。"""

    def on_scan_start(self, total_dirs: int) -> None:
        pass  # 静默，扫描很快

    def on_scan_progress(self, current_dir: str, files_found: int) -> None:
        print(f"  扫描: {current_dir} ({files_found} 张)")

    def on_diff_result(self, total_phone: int, new_count: int, conflict_count: int,
                       download_size_gb: float) -> None:
        print(f"  待下载总计: {new_count} 张, {download_size_gb:.2f} GB")

    def on_download_start(self, total_files: int, total_bytes: int) -> None:
        size_str = f"{total_bytes / (1024**3):.1f} GB" if total_bytes > 1024**3 else f"{total_bytes / (1024**2):.1f} MB"
        print(f"  开始下载 {total_files} 个文件 ({size_str})\n")

    def on_download_progress(self, index: int, total: int, filename: str,
                             speed_mbps: float, remaining_minutes: int,
                             downloaded_bytes: int) -> None:
        print(f"  [{index}/{total}] {filename}  {speed_mbps:.1f} MB/s  "
              f"剩余约 {remaining_minutes} 分钟  ({_fmt_bytes(downloaded_bytes)})")


def _fmt_bytes(n: int) -> str:
    """字节数格式化：KB/MB/GB。"""
    if n < 1024 ** 2:
        return f"{n / 1024:.0f} KB"
    elif n < 1024 ** 3:
        return f"{n / (1024 ** 2):.1f} MB"
    else:
        return f"{n / (1024 ** 3):.2f} GB"

    def on_download_file_error(self, filename: str, error: str) -> None:
        print(f"  [{filename}] 失败: {error}")

    def on_download_complete(self, success: int, failed: int, duration_secs: float) -> None:
        print(f"\n{'='*50}")
        mins = int(duration_secs // 60)
        secs = int(duration_secs % 60)
        print(f"同步完成: {success} 成功, {failed} 失败, 耗时 {mins}分{secs}秒")

    def on_status(self, message: str) -> None:
        print(f"  {message}")

    def on_error(self, message: str) -> None:
        print(f"  错误: {message}")
