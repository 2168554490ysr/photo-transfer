# 照片传输工具 — 设计规格

**日期**: 2026-07-12 | **状态**: 已实现

---

## 1. 概述

从 Android 手机通过 USB(ADB) 快速下载照片到 Windows PC。
通过 MediaStore 数据库扫描系统相册中所有照片，与 PC 已有文件比对去重，仅下载新照片。
按日期组织目录。

### 核心约束

| 维度 | 决策 |
|------|------|
| 连接方式 | 仅 USB (ADB) |
| 同步范围 | MediaStore 涵盖的全部照片 |
| 去重策略 | 文件名+大小快速筛 → 冲突默认视为重复跳过（`verify_conflicts` 开启时才用首尾哈希确认） |
| PC存储 | 按日期分子目录 `YYYY-MM-DD/` |
| 手机源文件 | 不删除，纯下载 |
| 实现语言 | Python |
| 断点续传 | 任务级（进度文件记录已完成项，中断可续） |

---

## 2. 架构

```
app/main.py                     # CLI 入口
modules/gui/gui.py              # GUI 入口（tkinter，与后端解耦）
config.json                     # 配置

lib/reporter.py                 # ProgressReporter 协议（解耦层）
lib/orchestrator.py             # SyncWorker 后台线程编排

modules/adb_connector/          # 模块 1: ADB 连接管理
modules/photo_scanner/          # 模块 2: 照片扫描与去重（含 MediaStore）
modules/photo_downloader/       # 模块 3: 下载调度 + 断点续传
```

数据流：

```
config.json ──▶ main.py / gui.py ──▶ orchestrator ──▶ adb_connector: 检测设备
                                                           │
                                                           ▼
                                                      photo_scanner: MediaStore 扫描 + 去重
                                                           │
                                                           ▼
                                                      photo_downloader: 预检 → 批量下载
                                                           │
                                                           ▼
                                                     .sync_progress.json (实时)
                                                     .sync_log.json      (完成时)
```

---

## 3. 模块设计

### 3.1 adb_connector — ADB 连接管理

**文件**: `modules/adb_connector/device.py`

- `check_device()` — USB 设备检测
- `list_files(device, path)` — 递归文件列表（find + xargs 批量 stat）
- `pull_file(device, remote, local)` — 单文件下载
- `get_device_info(device)` — 设备型号/版本/存储结构

### 3.2 photo_scanner — 照片扫描与去重

**文件**: `modules/photo_scanner/scanner.py`

- `scan_phone(device, paths)` — 目录扫描（传统方式）
- `scan_phone_mediastore(device)` — MediaStore 扫描（推荐）
- `scan_pc(target_dir)` — PC 文件索引
- `diff(phone, pc_index)` — 去重比对
- `hash_verify(device, conflicts)` — 手机端首尾哈希确认
- `build_download_list(new, confirmed)` — 构建下载清单

### 3.3 photo_downloader — 下载调度

**文件**: `modules/photo_downloader/downloader.py`

- `check_disk_space(target, size)` — 空间预检
- `download(device, file_list, target, reporter=None)` — 批量下载 + 断点续传 + 进度报告

### 3.4 gui — GUI 界面

**文件**: `modules/gui/gui.py`

- tkinter 实现，通过 `lib/reporter.py` 协议与后端解耦
- 实时进度条、文件级状态更新
- 后台线程执行同步，不阻塞 UI

---

## 4. 解耦设计

GUI 和后端通过 `lib/reporter.py` 中的 `ProgressReporter` 协议通信：

```
GUI (modules/gui/)          后端 (modules/*/)
      │                           │
      ├── GuiReporter ──实现──▶ ProgressReporter
      │                           │
      └── SyncWorker ───调用──▶ adb_connector
                                  photo_scanner
                                  photo_downloader (reporter 参数)
```

- GUI 不直接导入任何 `modules/*/` 模块
- `lib/orchestrator.py` 的 `SyncWorker` 在后台线程运行同步流程
- `lib/reporter.py` 提供 `ConsoleReporter`（CLI 用）和协议定义

---

## 5. 配置

**文件**: `config.json`

```json
{
  "phone_paths": ["__mediastore__"],
  "pc_target_dir": "D:/个人/相片"
}
```

---

## 6. CLI 用法

```
python app/main.py              # 完整同步
python app/main.py --scan        # 仅扫描去重
python app/main.py --explore     # 探索设备目录
python app/main.py --resume      # 续传

python modules/gui/gui.py        # 启动 GUI
```

---

## 7. 错误处理

| 场景 | 行为 |
|------|------|
| USB 设备未连接 | 报错退出 |
| ADB 命令超时 | 重试1次 |
| 磁盘空间不足 | 预检退出 |
| 单文件下载失败 | 重试1次，仍失败则跳过 |
| 权限不足 | 报错退出 |
