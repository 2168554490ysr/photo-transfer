"""照片传输工具 — 入口

用法:
  python app/main.py              # 完整同步流程
  python app/main.py --explore     # 探索手机目录结构（用于首次配置）
  python app/main.py --scan        # 仅扫描去重，输出待下载清单
  python app/main.py --resume      # 仅下载（使用已有进度文件）
"""

import sys
import os
import json
import argparse

# 将项目根目录加入 sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from modules import load_module
_m1 = load_module("adb_connector", "device")
check_device = _m1.check_device
get_device_info = _m1.get_device_info
AdbError = _m1.AdbError

_m2 = load_module("photo_scanner", "scanner")
scan_phone_mediastore = _m2.scan_phone_mediastore
scan_videos_mediastore = _m2.scan_videos_mediastore
scan_pc = _m2.scan_pc
diff = _m2.diff
hash_verify = _m2.hash_verify
build_download_list = _m2.build_download_list
PHOTO_EXTENSIONS = _m2.PHOTO_EXTENSIONS
VIDEO_EXTENSIONS = _m2.VIDEO_EXTENSIONS

_m3 = load_module("photo_downloader", "downloader")
download = _m3.download

CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def cmd_explore():
    """探索模式：显示设备信息和目录结构，辅助首次配置。"""
    print("=== 设备探索模式 ===\n")
    try:
        device = check_device()
        print(f"设备已连接: {device}\n")
        info = get_device_info(device)
        print(f"型号: {info['model']}")
        print(f"Android 版本: {info['android_version']}")
        print(f"\n/sdcard/ 目录内容:")
        for d in sorted(info["storage_roots"]):
            print(f"  {d}/")

        # 进一步探索 DCIM 目录（仅 ls，不做递归扫描）
        print(f"\n/sdcard/DCIM/ 目录内容:")
        _adb = _m1._adb
        try:
            ls_result = _adb('shell ls /sdcard/DCIM/', device)
            items = [x.strip() for x in ls_result.strip().split("\n") if x.strip()]
            # 统计每个子目录的文件数
            for item in sorted(items):
                if item.endswith("/"):
                    item = item[:-1]
                # 快速统计文件数
                try:
                    count_out = _adb(f'shell "find /sdcard/DCIM/{item} -type f | wc -l"', device)
                    count = count_out.strip()
                    print(f"  {item}/  ({count} 个文件)")
                except Exception:
                    print(f"  {item}/")
        except Exception as e:
            print(f"  无法访问 DCIM 目录: {e}")

        print(f"\n请将需要扫描的路径更新到 config.json 的 phone_paths 中。")
    except AdbError as e:
        print(f"错误: {e}")
        sys.exit(1)


def _sync_media(device: str, label: str, scan_fn, target_dir: str,
                extensions: set, scan_only: bool = False,
                verify_conflicts: bool = False) -> int:
    """同步一种媒体类型（照片或视频）。

    Returns:
        下载的文件数
    """
    print(f"\n{'='*50}")
    print(f"  {label}")
    print(f"{'='*50}")

    # 扫描手机
    print(f"  扫描手机{label} (MediaStore)...")
    phone_files = scan_fn(device)
    if not phone_files:
        print(f"  手机未发现{label}文件。")
        return 0
    phone_total = sum(f["size"] for f in phone_files)
    print(f"  发现 {len(phone_files)} 个{label}, 总大小 {phone_total / (1024**3):.1f} GB")

    # 去重
    print(f"  比对去重...  PC: {target_dir}")
    pc_index = scan_pc(target_dir, extensions)
    print(f"  PC 已有: {len(pc_index)} 个文件")

    new_files, conflict_files = diff(phone_files, pc_index)
    print(f"  新增: {len(new_files)}, 冲突: {len(conflict_files)}")

    if conflict_files:
        if verify_conflicts:
            print(f"  哈希确认 {len(conflict_files)} 个冲突文件...")
            hash_confirmed = hash_verify(device, conflict_files, verify=True)
        else:
            print(f"  按文件名+大小判定 {len(conflict_files)} 个冲突为已下载(跳过确认)")
            hash_confirmed = hash_verify(device, conflict_files, verify=False)
    else:
        hash_confirmed = []

    download_list = build_download_list(new_files, hash_confirmed)
    download_size = sum(f["size"] for f in download_list)
    print(f"  待下载: {len(download_list)} 个, {download_size / (1024**3):.2f} GB")

    if not download_list:
        print(f"  所有{label}已同步。")
        return 0

    if scan_only:
        print(f"\n  待下载清单（前 10 条）:")
        for f in download_list[:10]:
            print(f"    {f['local_subdir']}/{f['local_filename']}")
        if len(download_list) > 10:
            print(f"    ... 共 {len(download_list)} 个")
        return len(download_list)

    # 下载
    print(f"  开始下载...\n")
    result = download(device, download_list, target_dir)
    if result["errors"]:
        print(f"  有 {result['failed']} 个文件下载失败。")
    return result["success"]


def cmd_sync(scan_only: bool = False):
    """完整同步流程——照片 + 视频。"""
    print("=== 照片传输工具 ===\n")

    config = load_config()
    photo_dir = config["pc_photo_dir"]
    video_dir = config.get("pc_video_dir", "D:/个人/视频")
    verify_conflicts = bool(config.get("verify_conflicts", False))

    # 连接设备
    print("[1/5] 检测设备...")
    try:
        device = check_device()
        print(f"  设备已连接: {device}\n")
    except AdbError as e:
        print(f"  错误: {e}")
        sys.exit(1)

    # 同步照片
    photo_count = _sync_media(device, "照片", scan_phone_mediastore,
                              photo_dir, PHOTO_EXTENSIONS, scan_only, verify_conflicts)

    # 同步视频
    video_count = _sync_media(device, "视频", scan_videos_mediastore,
                              video_dir, VIDEO_EXTENSIONS, scan_only, verify_conflicts)

    print(f"\n{'='*50}")
    print(f"全部完成: 照片 {photo_count} 张, 视频 {video_count} 段")


def cmd_resume():
    """仅下载模式：使用进度文件续传。"""
    print("=== 续传模式 ===\n")

    config = load_config()
    pc_target = config.get("pc_photo_dir", config.get("pc_target_dir", "D:/个人/相片"))

    try:
        device = check_device()
        print(f"设备已连接: {device}\n")
    except AdbError as e:
        print(f"错误: {e}")
        sys.exit(1)

    print("从进度文件恢复下载...")
    print("(如需重新扫描去重，请运行 python app/main.py)")
    # 续传直接调用 download，传入空列表让它只做进度恢复
    result = download(device, [], pc_target)
    if result["errors"]:
        print(f"\n有 {result['failed']} 个文件失败，可再次运行续传。")


def main():
    parser = argparse.ArgumentParser(description="从 Android 手机同步照片到 PC")
    parser.add_argument("--explore", action="store_true", help="探索手机目录结构")
    parser.add_argument("--scan", action="store_true", help="仅扫描去重，不下载")
    parser.add_argument("--resume", action="store_true", help="仅下载（从进度文件恢复）")
    args = parser.parse_args()

    if args.explore:
        cmd_explore()
    elif args.resume:
        cmd_resume()
    else:
        cmd_sync(scan_only=args.scan)


if __name__ == "__main__":
    main()
