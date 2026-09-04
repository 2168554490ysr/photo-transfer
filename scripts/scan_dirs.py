"""扫描手机照片分布情况。"""
import sys
sys.path.insert(0, ".")

from modules import load_module

m1 = load_module("adb_connector", "device")
device = m1.check_device()
print(f"设备: {device} ({m1.get_device_info(device)['model']})\n")

# 扫描多个可能的照片目录
dirs_to_check = [
    "/sdcard/DCIM/Camera",
    "/sdcard/DCIM/Screenshots",
    "/sdcard/DCIM/Creative",
    "/sdcard/DCIM/CamScanner",
    "/sdcard/DCIM/ScreenRecorder",
    "/sdcard/DCIM/Notes",
    "/sdcard/DCIM/captured_media",
    "/sdcard/DCIM/douyin",
    "/sdcard/Pictures",
    "/sdcard/Download",
]

print("=== 各目录照片统计 ===\n")
total = 0
for d in dirs_to_check:
    try:
        files = m1.list_files(device, d)
        photos = [f for f in files if any(
            f["name"].lower().endswith(ext)
            for ext in (".jpg", ".jpeg", ".png", ".gif", ".heic", ".webp", ".bmp")
        )]
        if photos:
            size_mb = sum(f["size"] for f in photos) / (1024 * 1024)
            print(f"  {d}: {len(photos)} 张, {size_mb:.1f} MB")
            total += len(photos)
        else:
            print(f"  {d}: (无照片)")
    except Exception as e:
        print(f"  {d}: 错误 - {e}")

print(f"\n总计: {total} 张照片")

# 还差多少到7701
print(f"相册总数 7701, 已找到 {total}, 差距 {7701 - total}")
if 7701 - total > 0:
    print("\n可能存在其他来源目录，建议将 phone_paths 设为 ['/sdcard/DCIM/Camera', '/sdcard/DCIM/Screenshots'] 等")
