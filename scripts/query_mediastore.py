"""查询 Android MediaStore，找到相册中所有照片的来源目录。"""
import sys
sys.path.insert(0, ".")

from modules import load_module

m1 = load_module("adb_connector", "device")
device = m1.check_device()
adb = m1._adb

print("=== 查询 MediaStore 照片数据库 ===\n")

# 查询所有图片的目录分布
# bucket_display_name = 目录名, _data = 完整路径
cmd = (
    'shell "content query --uri content://media/external/images/media '
    '--projection bucket_display_name:_data '
    '--sort bucket_display_name"'
)

try:
    out = adb(cmd, device)
    lines = out.strip().split("\n")

    # 按目录分组统计
    from collections import Counter
    dirs = Counter()
    examples = {}

    current_row = {}
    for line in lines:
        line = line.strip()
        if line.startswith("Row:"):
            if current_row:
                bucket = current_row.get("bucket_display_name", "未知")
                path = current_row.get("_data", "")
                dirs[bucket] += 1
                if bucket not in examples:
                    examples[bucket] = path
            current_row = {}
        elif "=" in line:
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip()
            current_row[key] = val

    # 处理最后一行
    if current_row:
        bucket = current_row.get("bucket_display_name", "未知")
        path = current_row.get("_data", "")
        dirs[bucket] += 1
        if bucket not in examples:
            examples[bucket] = path

    print("相册按目录分布:\n")
    total = 0
    for bucket, count in dirs.most_common():
        total += count
        example = examples.get(bucket, "")
        # 提取父目录路径
        parent = "/".join(example.split("/")[:-1]) if example else ""
        print(f"  {bucket:30s}  {count:>6} 张  例: {parent}")

    print(f"\n总计: {total} 张照片 (MediaStore 记录)")

except Exception as e:
    print(f"查询失败: {e}")
    print("尝试备用方案: 用 find 按扩展名搜索...")
