"""分析 MediaStore 中照片的目录分布"""
import sys
sys.path.insert(0, ".")

from modules import load_module
from collections import Counter
import os

m1 = load_module("adb_connector", "device")
adb = m1._adb
device = m1.check_device()

out = adb(
    'shell "content query --uri content://media/external/images/media '
    '--projection _data:bucket_display_name"',
    device,
)

# Parse: Row: N _data=PATH, bucket_display_name=NAME
dirs = Counter()
examples = {}

for line in out.split("\n"):
    line = line.strip()
    if not line.startswith("Row:"):
        continue
    # Extract _data
    data_start = line.find("_data=") + 6
    data_end = line.find(", bucket_display_name=")
    if data_start < 6 or data_end < 0:
        continue
    path = line[data_start:data_end]
    bucket_start = line.find("bucket_display_name=") + 20
    bucket = line[bucket_start:] if bucket_start > 19 else "Unknown"

    dirs[bucket] += 1
    if bucket not in examples:
        # Show parent directory
        examples[bucket] = os.path.dirname(path)

print(f"总记录数: {sum(dirs.values())}\n")
print(f"{'相册名称':<30s} {'数量':>6s}  {'来源目录'}")
print("-" * 70)
for bucket, count in dirs.most_common():
    print(f"{bucket:<30s} {count:>6d}  {examples[bucket]}")
