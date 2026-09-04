# 模块 gui — L2 架构约束

---

## ARC-01: ProgressReporter 协议解耦

**决策**: GUI 通过 `lib/reporter.py` 中定义的 `ProgressReporter` 协议与后端通信，不直接调用业务模块。

**理由**: 后端模块可独立测试、CLI 和 GUI 共享同一套逻辑。变更 GUI 不影响后端，反之亦然。

---

## ARC-02: 后台线程 + after() 回调

**决策**: 同步流程在 `threading.Thread` 中运行，GUI 更新通过 `root.after(0, callback)` 提交到主线程。

**理由**: tkinter 不是线程安全的，所有控件更新必须在主线程执行。`after()` 是 tkinter 提供的线程间安全通信机制。

---

## ARC-03: SyncWorker 编排器

**决策**: `lib/orchestrator.py` 中的 `SyncWorker` 封装完整的同步流程（连接→扫描→去重→下载），通过 reporter 报告每一步的状态。

**理由**: GUI 只需知道"开始"和"进度"，不需要了解内部步骤顺序。编排器可复用于不同的 UI 层。

---

## ARC-04: tkinter 标准库

**决策**: 使用 Python 标准库 tkinter，不引入第三方 GUI 框架。

**理由**: 零额外依赖，Windows/macOS/Linux 均可运行。功能足够满足需求。

---

## ARC-05: 字节驱动进度条 + 大文件实时轮询

**决策**: 进度条按**累计下载字节 / 总字节**推进（非文件计数），并显示百分比。超过 8MB 的大文件在下载中由后端轮询目标文件大小、实时上报字节进度。

**理由**:
- 文件大小差异大（几 MB 照片 vs 上百 MB 视频），按文件计数推进无法反映真实进度；字节驱动更准确
- 大文件下载耗时长，若只在文件完成后更新，进度条会长时间停滞造成"卡死"假象；轮询文件大小实现边下边走
- GUI 通过 `ProgressReporter.on_download_progress` 接收 `downloaded_bytes`，与后端解耦（沿用 ARC-01）
- 界面统一配色/卡片布局仅使用 ttk 样式，不引入第三方库（沿用 ARC-04）

---

## ARC-06: 目录配置（Entry + filedialog + 持久化）

**决策**: 目标目录在 GUI 内通过 `ttk.Entry` 编辑、`tkinter.filedialog.askdirectory` 选择；"保存目录"写回 `config.json`（仅更新目录字段，保留 `phone_paths`/`verify_conflicts` 等）。

**理由**:
- 满足用户在界面直接调整目标目录的需求，无需手动改 `config.json`
- 仅使用 tkinter 标准库（`filedialog`），符合 ARC-04 零额外依赖
- 写回时只改目录字段，避免覆盖其他配置
- GUI 仍不导入业务模块，目录仅作为参数传给 `SyncWorker`（沿用 ARC-01 解耦）
