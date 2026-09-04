"""查询 MediaStore 视频数据库，分析视频存储分布。"""
import sys
sys.path.insert(0, ".")

from modules import load_module
from collections import Counter
import os

m1 = load_module("adb_connector", "device")
adb = m1._adb
device = m1.check_device()

# 查询视频
out = adb(
    'shell "content query --uri content://media/external/video/media '
    '--projection _data:_size:_display_name:datetaken:bucket_display_name"',
    device,
)

buckets = Counter()
total_count = 0
total_size = 0
examples = {}

for line in out.split("\n"):
    line = line.strip()
    if not line.startswith("Row:"):
        continue

    # 简单解析
    data_start = line.find("_data=") + 6
    data_end = line.find(", _size=")
    if data_start < 6 or data_end < 0:
        continue
    path = line[data_start:data_end]

    size_start = line.find("_size=") + 6
    size_end = line.find(",", size_start) if "," in line[size_start:] else len(line)
    size_str = line[size_start:size_end] if size_end > size_start else "0"

    bucket_start = line.find("bucket_display_name=")
    bucket = line[bucket_start+20:] if bucket_start > 0 else "Unknown"

    try:
        size = int(size_str) if size_str else 0
    except ValueError:
        size = 0

    buckets[bucket] += 1
    total_count += 1
    total_size += size

    if bucket not in examples:
        examples[bucket] = os.path.dirname(path)

print(f"MediaStore 视频总数: {total_count}")
print(f"总大小: {total_size / (1024**3):.2f} GB\n")

print(f"{'相册名称':<30s} {'数量':>6s}  {'来源目录'}")
print("-" * 70)
for bucket, count in buckets.most_common():
    print(f"{bucket:<30s} {count:>6d}  {examples[bucket]}")
