"""测试 MediaStore 扫描"""
import sys
sys.path.insert(0, ".")

from modules import load_module

m1 = load_module("adb_connector", "device")
m2 = load_module("photo_scanner", "scanner")

device = m1.check_device()
print(f"设备: {device} ({m1.get_device_info(device)['model']})\n")

print("正在通过 MediaStore 扫描照片...")
files = m2.scan_phone_mediastore(device)

print(f"MediaStore 照片总数: {len(files)}")
total_mb = sum(f["size"] for f in files) / (1024 * 1024)
print(f"总大小: {total_mb:.1f} MB ({total_mb/1024:.1f} GB)")

# 抽样显示
print(f"\n前 5 条:")
for f in files[:5]:
    print(f"  {f['name']:40s} {f['size']:>10d}  mtime={f['mtime']}")

# 按目录统计（只显示一级父目录）
from collections import Counter
dirs = Counter()
for f in files:
    parent = "/".join(f["path"].split("/")[:-1])
    top = parent.replace("/storage/emulated/0/", "").split("/")[0]
    dirs[top] += 1

print(f"\n按顶级目录分布:")
for d, c in dirs.most_common():
    print(f"  /sdcard/{d}: {c} 张")
