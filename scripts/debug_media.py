"""Debug MediaStore output format."""
import sys
sys.path.insert(0, ".")

from modules import load_module
m1 = load_module("adb_connector", "device")
adb = m1._adb
device = m1.check_device()

# 先看有多少记录
count_out = adb(
    'shell "content query --uri content://media/external/images/media --projection _id | wc -l"',
    device,
)
print("MediaStore image rows:", count_out.strip())

# 看前几条原始输出
out = adb(
    'shell "content query --uri content://media/external/images/media '
    '--projection _data:bucket_display_name"',
    device,
)
lines = out.split("\n")
print(f"Total output lines: {len(lines)}")
for line in lines[:50]:
    print(repr(line))
