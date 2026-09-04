# 模块 adb_connector — 进度追溯矩阵

## 变更记录

| 日期 | 变更内容 | 关联 REQ | 代码文件 | 测试文件 | 状态 |
|------|---------|---------|---------|---------|------|
| 2026-07-12 | 初始设计：L1/L2 文档创建 | REQ-01~05 | — | — | 完成 |
| 2026-07-12 | 实现 device.py | REQ-01~05 | `adb_connector/device.py` | — | 完成 |
| 2026-07-12 | 测试用例 | REQ-01~05 | — | `adb_connector/tests/test_device.py` | 12/12 通过 |
| 2026-07-12 | 优化：xargs批量stat | REQ-02 | `device.py` | — | 完成 |
| 2026-07-12 | 修复：shlex.split + UTF-8编码 | REQ-02 | `device.py` | — | 完成 |
| 2026-07-12 | 优化：重构 _run 重试 + 新增 adb_shell | REQ-05 | `device.py` | — | 完成 |
| 2026-07-12 | 优化：pull_file 接受 file_size 跳过 stat | REQ-03 | `device.py` | `test_device.py` | 46/46 通过 |
| 2026-07-12 | 修复：GUI/pythonw 下 adb 弹黑框——子进程加 CREATE_NO_WINDOW | REQ-05 | `device.py` | `test_device.py` | 47/47 通过 |
| 2026-07-12 | 关闭/取消即停止：_run 改 Popen 可终止 + kill_all_adb + 取消不重试 | REQ-05 | `device.py`、`orchestrator.py` | `test_device.py` | 49/49 通过 |
| 2026-07-12 | 模块重命名：1 → adb_connector | — | 全部 | 全部 | 完成 |

## 追溯矩阵

| REQ | 描述 | 实现位置 | 测试 | 状态 |
|-----|------|---------|------|------|
| REQ-01 | USB 设备检测 | `check_device()` | TestCheckDevice (4) | 完成 |
| REQ-02 | 文件列表获取 | `list_files()` | TestListFiles (3) | 完成 |
| REQ-03 | 单文件下载（可跳过 stat） | `pull_file()` | TestPullFile (2) | 完成 |
| REQ-04 | 设备信息获取 | `get_device_info()` | TestGetDeviceInfo (1) | 完成 |
| REQ-05 | 超时与重试 + 无窗口运行 + 取消不重试 | `_adb()` / `_run()` / `kill_all_adb()` | TestTimeoutRetry (2) + TestNoWindowSubprocess (1) + TestCancel (2) | 完成 |
