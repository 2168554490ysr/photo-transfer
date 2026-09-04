"""模块 2 — 照片扫描与去重

@req REQ-01: 手机照片扫描
@req REQ-02: PC 文件索引
@req REQ-03: 去重比对
@req REQ-04: 哈希确认
@req REQ-05: 待下载清单输出

文件名+大小快速去重，冲突时手机端算首尾哈希确认。
"""

import os
import hashlib
import json
from datetime import datetime
from typing import Optional

from modules import load_module as _load_module
_m1_device = _load_module("adb_connector", "device")
_adb = _m1_device._adb
_adb_shell = _m1_device.adb_shell

# 支持的照片扩展名
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".heic", ".webp", ".bmp"}
# 支持的视频扩展名
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".3gp", ".webm", ".m4v", ".ts"}
# 哈希采样大小
HASH_SAMPLE_BYTES = 64 * 1024  # 64KB
# PC 哈希缓存文件
HASH_CACHE_FILE = ".pc_hash_cache.json"


def _is_photo(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()
    return ext in PHOTO_EXTENSIONS


def _is_video(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()
    return ext in VIDEO_EXTENSIONS


# @req REQ-01: 手机照片扫描
def scan_phone(device: str, paths: list[str]) -> list[dict]:
    """扫描手机上指定路径的照片文件。

    Args:
        device: 设备序列号
        paths: 手机端目录路径列表

    Returns:
        [{name, size, mtime, path}, ...] 仅照片文件
    """
    all_files = []
    for p in paths:
        try:
            files = _m1_device.list_files(device, p)
            all_files.extend(files)
        except Exception as e:
            print(f"  警告: 扫描 {p} 失败: {e}")

    # 过滤仅保留照片扩展名
    photos = [f for f in all_files if _is_photo(f["name"])]
    return photos


# @req REQ-01: 手机照片扫描（MediaStore 方式）
def scan_phone_mediastore(device: str) -> list[dict]:
    """通过 MediaStore 数据库扫描手机所有照片（与系统相册一致）。

    查询 content://media/external/images/media，获取所有图片记录。
    返回格式与 scan_phone 一致。

    Args:
        device: 设备序列号

    Returns:
        [{name, size, mtime, path}, ...] 所有 MediaStore 记录的照片
    """
    cmd = (
        'shell "content query --uri content://media/external/images/media '
        '--projection _data:_size:_display_name:datetaken:date_modified"'
    )
    output = _m1_device._adb(cmd, device)

    files = []
    for line in output.split("\n"):
        line = line.strip()
        if not line.startswith("Row:"):
            continue

        # 解析 Row: N _data=PATH, _size=SIZE, _display_name=NAME, datetaken=MS, date_modified=SEC
        try:
            data = _parse_row(line)
            path = data.get("_data", "")
            if not path or not os.path.splitext(path)[1].lower() in PHOTO_EXTENSIONS:
                continue

            name = data.get("_display_name", path.split("/")[-1])
            size_str = data.get("_size", "0")
            size = int(size_str) if size_str else 0

            # 优先用 datetaken（毫秒），回退到 date_modified（秒）
            datetaken_str = data.get("datetaken", "0")
            if datetaken_str and datetaken_str != "0":
                mtime = int(datetaken_str) // 1000
            else:
                date_mod_str = data.get("date_modified", "0")
                mtime = int(date_mod_str) if date_mod_str else 0

            files.append({
                "name": name,
                "size": size,
                "mtime": mtime,
                "path": path,
            })
        except (ValueError, KeyError):
            continue

    files.sort(key=lambda f: f["path"])
    return files


def scan_videos_mediastore(device: str) -> list[dict]:
    """通过 MediaStore 数据库扫描手机所有视频（与系统相册一致）。

    查询 content://media/external/video/media，获取所有视频记录。

    Args:
        device: 设备序列号

    Returns:
        [{name, size, mtime, path}, ...] 所有 MediaStore 记录的视频
    """
    cmd = (
        'shell "content query --uri content://media/external/video/media '
        '--projection _data:_size:_display_name:datetaken:date_modified"'
    )
    output = _m1_device._adb(cmd, device)

    files = []
    for line in output.split("\n"):
        line = line.strip()
        if not line.startswith("Row:"):
            continue

        try:
            data = _parse_row(line)
            path = data.get("_data", "")
            if not path or os.path.splitext(path)[1].lower() not in VIDEO_EXTENSIONS:
                continue

            name = data.get("_display_name", path.split("/")[-1])
            size_str = data.get("_size", "0")
            size = int(size_str) if size_str else 0

            datetaken_str = data.get("datetaken", "0")
            if datetaken_str and datetaken_str != "0":
                mtime = int(datetaken_str) // 1000
            else:
                date_mod_str = data.get("date_modified", "0")
                mtime = int(date_mod_str) if date_mod_str else 0

            files.append({
                "name": name,
                "size": size,
                "mtime": mtime,
                "path": path,
            })
        except (ValueError, KeyError):
            continue

    files.sort(key=lambda f: f["path"])
    return files


def _parse_row(line: str) -> dict[str, str]:
    """解析 MediaStore content query 的一行输出。

    格式: Row: N key1=val1, key2=val2, ...
    val1 中可能含逗号（如路径含 Unicode 逗号），但 key=value 之间用 ", " 分隔。
    安全的解析方式：从 Row: N  之后，按 ", key=" 模式分割。
    """
    # 移除 "Row: N " 前缀
    body = line.split(" ", 2)[-1] if " " in line else line
    result = {}
    # 用 ", key=" 的分隔方式不可靠，改用正则
    import re
    # 匹配 key=value 对，value 直到下一个 " key=" 或行尾
    pattern = re.compile(r'(\w+)=(.+?)(?=,\s*\w+=|$)')
    for match in pattern.finditer(body):
        key = match.group(1)
        val = match.group(2).rstrip(", ")
        result[key] = val
    return result


# @req REQ-02: PC 文件索引
def scan_pc(target_dir: str, extensions: set[str] | None = None) -> dict[tuple, str]:
    """扫描 PC 目标目录，构建 (name, size) → full_path 索引。

    Args:
        target_dir: PC 端目录根路径
        extensions: 文件扩展名集合，默认 PHOTO_EXTENSIONS

    Returns:
        {(filename, filesize): full_path}
    """
    if extensions is None:
        extensions = PHOTO_EXTENSIONS
    index: dict[tuple, str] = {}
    if not os.path.isdir(target_dir):
        os.makedirs(target_dir, exist_ok=True)
        return index

    for root, _dirs, files in os.walk(target_dir):
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in extensions:
                continue
            full = os.path.join(root, fn)
            try:
                stat = os.stat(full)
                index[(fn, stat.st_size)] = full
            except OSError:
                continue
    return index


# @req REQ-03: 去重比对
def diff(phone_files: list[dict], pc_index: dict[tuple, str]) -> tuple[list[dict], list[dict]]:
    """比对手机文件与 PC 索引，分类为 new_files 和 conflict_files。

    Args:
        phone_files: 手机端照片文件列表
        pc_index: PC 端 {(name, size): path} 索引

    Returns:
        (new_files, conflict_files)
    """
    new_files = []
    conflict_files = []

    for f in phone_files:
        key = (f["name"], f["size"])
        if key not in pc_index:
            new_files.append(f)
        else:
            conflict_files.append({**f, "pc_path": pc_index[key]})

    return new_files, conflict_files


# @req REQ-04: 冲突判定与去重确认
def hash_verify(device: str, conflict_files: list[dict],
                reporter: Optional[object] = None, verify: bool = True) -> list[dict]:
    """处理去重冲突文件。

    默认策略（verify=False）：冲突视为重复，直接跳过（不哈希），返回空。
    严格模式（verify=True）：在手机上计算首尾哈希与 PC 端比对确认；
        哈希匹配 → 跳过（重复）；不匹配 → 加入下载清单（文件名加 _1 后缀）。
        已确认重复的 `(name, size)` 缓存标为 confirmed，后续运行跳过手机端哈希。

    Args:
        device: 设备序列号
        conflict_files: 冲突文件列表 [{name, size, mtime, path, pc_path}]
        reporter: 可选进度报告器，None 则打印粗粒度进度
        verify: 是否执行首尾哈希确认（严格模式）。False 则冲突一律视为重复跳过

    Returns:
        需要下载的文件列表（真正不同的文件）
    """
    if not conflict_files:
        return []
    if not verify:
        # 默认策略：信任 (文件名, 大小) 相同即重复，直接跳过，不做哈希
        return []

    # 加载 PC 哈希缓存
    pc_hash_cache = _load_hash_cache()

    # 大文件阈值：超过此大小的文件跳过手机端哈希（避免 dd 读取大文件耗时）
    LARGE_FILE_BYTES = 100 * 1024 * 1024  # 100MB

    total = len(conflict_files)
    # 进度上报粒度：约 100 次，避免刷屏
    step = max(1, total // 100)
    download_list = []
    for i, f in enumerate(conflict_files, 1):
        # 进度反馈（每步粒度触发，覆盖所有分支）
        if reporter and (i % step == 0 or i == total):
            reporter.on_status(f"哈希确认 {i}/{total} ...")
        elif reporter is None and (i % step == 0 or i == total):
            print(f"  哈希确认 {i}/{total} ...")

        key = (f["name"], f["size"])
        entry = pc_hash_cache.get(key) or {}

        # 已确认重复：跳过手机端哈希
        if entry.get("confirmed") and entry.get("pc_hash"):
            continue

        # 大文件（如视频）在手机上算哈希太慢，直接加入下载清单
        if f["size"] > LARGE_FILE_BYTES:
            download_list.append(f)
            continue

        # PC 端算首尾哈希（带缓存）；None 表示 PC 端读取失败，保守按不同处理
        pc_hash = _pc_file_hash_cached(f["pc_path"], pc_hash_cache, f["size"])
        if pc_hash is None:
            download_list.append(f)
            continue

        # 手机端算首尾哈希（单次 adb 调用）
        phone_hash = _phone_file_hash(device, f["path"])
        if not phone_hash:
            # 计算失败，保守处理：加入下载清单
            download_list.append(f)
            continue

        if phone_hash == pc_hash:
            # 哈希一致，确认为重复，记录缓存并跳过
            entry["pc_hash"] = pc_hash
            entry["confirmed"] = True
            pc_hash_cache[key] = entry
            continue
        else:
            # 哈希不一致，不同的文件，加 _1 后缀
            name_parts = os.path.splitext(f["name"])
            new_name = f"{name_parts[0]}_1{name_parts[1]}"
            download_list.append({**f, "name": new_name})

    # 保存 PC 哈希缓存
    _save_hash_cache(pc_hash_cache)

    return download_list


# @req REQ-05: 待下载清单输出
def build_download_list(new_files: list[dict], hash_confirmed: list[dict]) -> list[dict]:
    """构建最终下载清单，添加 local_subdir 和 local_filename。

    Args:
        new_files: 确定是新文件的列表
        hash_confirmed: 哈希确认后需要下载的冲突文件

    Returns:
        [{name, size, mtime, phone_path, local_subdir, local_filename}]
    """
    result = []
    for f in new_files + hash_confirmed:
        dt = datetime.fromtimestamp(f["mtime"])
        subdir = dt.strftime("%Y-%m-%d")
        result.append({
            "name": f["name"],
            "size": f["size"],
            "mtime": f["mtime"],
            "phone_path": f["path"],
            "local_subdir": subdir,
            "local_filename": f["name"],
        })
    # 按日期 + 文件名排序
    result.sort(key=lambda x: (x["local_subdir"], x["name"]))
    return result


def _phone_file_hash(device: str, remote_path: str) -> Optional[str]:
    """单次 adb 调用计算手机端首尾 64KB 的 MD5 哈希。

    采样规则与 PC 端 `_pc_file_hash` 完全一致：
      - 文件 <= 128KB 用全文件哈希（full|full）
      - 否则取 首64KB | 尾64KB（尾部用 shell `tail -c` 精确读取，与 PC `seek(-64K, END)` 对齐）

    用 `adb_shell` 把整段脚本作为单个 argv 传给 adb，一次往返完成 stat + head + tail。

    Returns:
        "head_md5|tail_md5" 或 None（计算失败时）
    """
    try:
        # 路径含单引号时做 shell 转义（极少见，防御性处理）
        safe_path = remote_path.replace("'", "'\\''")
        script = (
            "f='" + safe_path + "'; "
            'sz=$(stat -c %s "$f" 2>/dev/null); '
            'if [ "$sz" -le 131072 ]; then '
            'm=$(md5sum "$f" 2>/dev/null); echo "$sz|${m%% *}|${m%% *}"; '
            'else h=$(dd if="$f" bs=64K count=1 2>/dev/null | md5sum); '
            't=$(tail -c 65536 "$f" 2>/dev/null | md5sum); '
            'echo "$sz|${h%% *}|${t%% *}"; fi'
        )
        out = _adb_shell(device, script)
        parts = out.strip().split("|")
        if len(parts) == 3:
            head = parts[1].strip()
            tail = parts[2].strip()
            if head and tail:
                return f"{head}|{tail}"
        return None
    except Exception:
        return None


def _pc_file_hash(path: str) -> Optional[str]:
    """计算 PC 端文件的首尾 64KB MD5 哈希。"""
    try:
        file_size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if file_size <= HASH_SAMPLE_BYTES * 2:
                full = fh.read()
                h = hashlib.md5(full).hexdigest()
                return f"{h}|{h}"
            head = fh.read(HASH_SAMPLE_BYTES)
            fh.seek(-HASH_SAMPLE_BYTES, os.SEEK_END)
            tail = fh.read(HASH_SAMPLE_BYTES)
        head_hash = hashlib.md5(head).hexdigest()
        tail_hash = hashlib.md5(tail).hexdigest()
        return f"{head_hash}|{tail_hash}"
    except Exception:
        return None


def _load_hash_cache() -> dict:
    """加载 PC 哈希缓存。

    缓存 key 为 (name, size)，值为 {"pc_hash": str, "confirmed": bool}。
    兼容旧格式（值为纯 hash 字符串）——自动迁移为未确认。
    """
    try:
        with open(HASH_CACHE_FILE, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        # 将字符串 key 转回 tuple
        result = {}
        for k, v in raw.items():
            parts = k.split("||")
            if len(parts) == 2:
                if isinstance(v, str):
                    result[(parts[0], int(parts[1]))] = {"pc_hash": v, "confirmed": False}
                elif isinstance(v, dict):
                    result[(parts[0], int(parts[1]))] = {
                        "pc_hash": v.get("pc_hash"),
                        "confirmed": bool(v.get("confirmed", False)),
                    }
        return result
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_hash_cache(cache: dict) -> None:
    """保存 PC 哈希缓存。tuple key 序列化为字符串。"""
    raw = {"||".join(str(x) for x in k): v for k, v in cache.items()}
    with open(HASH_CACHE_FILE, "w", encoding="utf-8") as fh:
        json.dump(raw, fh, ensure_ascii=False, indent=2)


def _pc_file_hash_cached(path: str, cache: dict, file_size: int) -> Optional[str]:
    """带缓存的 PC 文件哈希计算。

    缓存条目为 dict：{"pc_hash": str, "confirmed": bool}。
    返回 PC 端哈希字符串；计算失败返回 None。
    """
    name = os.path.basename(path)
    key = (name, file_size)
    entry = cache.get(key)
    if isinstance(entry, str):
        entry = {"pc_hash": entry, "confirmed": False}
        cache[key] = entry
    if entry is None:
        entry = {"pc_hash": None, "confirmed": False}
        cache[key] = entry
    if not entry.get("pc_hash"):
        h = _pc_file_hash(path)
        if h:
            entry["pc_hash"] = h
    return entry.get("pc_hash")
