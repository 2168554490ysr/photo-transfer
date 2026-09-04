# 模块 photo_scanner — 进度追溯矩阵

## 变更记录

| 日期 | 变更内容 | 关联 REQ | 代码文件 | 测试文件 | 状态 |
|------|---------|---------|---------|---------|------|
| 2026-07-12 | 初始设计：L1/L2 文档创建 | REQ-01~05 | — | — | 完成 |
| 2026-07-12 | 实现 scanner.py | REQ-01~05 | `photo_scanner/scanner.py` | — | 完成 |
| 2026-07-12 | 测试用例 | REQ-01~05 | — | `photo_scanner/tests/test_scanner.py` | 13/13 通过 |
| 2026-07-12 | 新增 MediaStore 扫描方式 | REQ-01 | `scanner.py` | — | 完成 |
| 2026-07-12 | 模块重命名：2 → photo_scanner | — | 全部 | 全部 | 完成 |
| 2026-07-12 | 性能优化：手机端哈希单次 adb 调用 + 已确认重复缓存复用 + 进度反馈 | REQ-04 | `scanner.py`、`device.py`、`orchestrator.py` | `test_scanner.py` | 21/21 通过 |
| 2026-07-12 | 去重策略变更：冲突默认视为重复跳过（`verify_conflicts` 开关开启时才做哈希确认） | REQ-04 | `scanner.py`、`orchestrator.py`、`main.py`、`config.json` | `test_scanner.py` | 45/45 通过 |

## 追溯矩阵

| REQ | 描述 | 实现位置 | 测试 | 状态 |
|-----|------|---------|------|------|
| REQ-01 | 手机照片扫描 | `scan_phone()` / `scan_phone_mediastore()` | TestScanPhone (1) | 完成 |
| REQ-02 | PC 文件索引 | `scan_pc()` | TestScanPc (4) | 完成 |
| REQ-03 | 去重比对 | `diff()` | TestDiff (3) | 完成 |
| REQ-04 | 冲突判定与去重确认（默认跳过；严格模式哈希确认） | `hash_verify()` / `_phone_file_hash()` / `_pc_file_hash_cached()` | TestHashVerify (8) + TestHashCache (2) | 完成 |
| REQ-05 | 待下载清单输出 | `build_download_list()` | TestBuildDownloadList (2) + TestIsPhoto (2) | 完成 |
