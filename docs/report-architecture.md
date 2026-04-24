# AI 报告架构

这份文档只描述当前仓库已经落地的实现。

## 1. 目标

报告页已经不再依赖按场景返回的静态报告，而是按真实 `sessionId` 生成整场分析。

当前前端不再暴露场景切换入口，新会话默认使用 `general` 通用表达训练。旧的 `host` 场景仍可被后端兼容读取，但报告 prompt 不再把它提示为“主持场景”，避免报告文案被固定到主持话术。

当前实现的目标只有两个：

- 训练过程中持续沉淀可追溯证据
- 点击生成报告时尽量复用离线产物，减少最终等待时间

## 2. 输入证据

报告侧只吃后端沉淀后的结构化证据，不直接读取原始音视频流。

当前保留的 artifact 包括：

- `transcript_final`
- `transcript_merged`
- `qa_question`
- `coach_signal`
- `coach_panel_snapshot`
- `session_finished`

其中：

- `qa_question` 记录 AI 问答里的提问文本
- `coach_signal` 记录 AI Live Coach 的结构化信号，包括 `subDimensionId / signalPolarity / severity / confidence / evidenceText`

## 3. 运行流程

### 3.1 训练中

`session_manager` 会把 transcript、QA 提问和 coach patch 持续写入报告侧存储。

同时会启动 `report.window_task`，按固定周期尝试构建新窗口：

- `REPORT_WINDOW_BUILD_INTERVAL_SECONDS=120`
- `REPORT_WINDOW_MIN_MS=180000`

窗口构建产物是 `window pack`，不是最终报告。

### 3.2 结束训练

`finish_session()` 会：

1. 标记 session finished
2. 取消周期窗口任务
3. 再补一轮可落盘窗口

### 3.3 生成报告

`POST /api/session/{session_id}/report/generate` 会：

1. 再次补齐所有可用窗口
2. 读取已有 `window pack`
3. 读取 `lastCoveredMs` 之后的尾窗原始数据
4. 把 `window pack + tail bundle` 一次性交给 `ReportBrainService.build_final_report()`
5. 保存最终报告并更新状态

当前不再做前端 section streaming，报告是一次性生成、一次性落盘。

## 4. 六个固定维度

报告固定使用以下 6 个一级维度：

- `body`：肢体
- `facial_expression`：表情
- `vocal_tone`：语音语调
- `rhythm`：节奏
- `content_quality`：内容质量
- `expression_structure`：表达结构

当前总分权重：

- 肢体 `20`
- 表情 `20`
- 语音语调 `10`
- 节奏 `20`
- 内容质量 `10`
- 表达结构 `20`

实现位置见 [report_domain.py](../backend/app/services/report_domain.py)。

## 5. 模型职责

### `ReportBrainService`

负责两件事：

- `build_window_pack`
- `build_final_report`

当前默认模型：

- `ALIYUN_REPORT_WINDOW_MODEL=qwen-plus-latest`
- `ALIYUN_REPORT_BRAIN_MODEL=qwen-plus-latest`
- `ALIYUN_REPORT_BRAIN_FALLBACK_MODEL=qwen-max-latest`

### `AI Live Coach`

Live Coach 仍然只负责实时反馈，不负责赛后整场归纳。

报告侧只复用它沉淀下来的结构化信号，不复用实时展示逻辑。

## 6. 存储方式

当前报告链路已经落盘到本地文件系统，不是纯内存态。

- artifact：`output/report_data/<session_id>/session_artifacts.jsonl`
- state：`output/report_data/<session_id>/report_state.json`
- windows：`output/report_data/<session_id>/windows/*.json`
- final：`output/report_data/<session_id>/final_report.json`

实现位置：

- [report_artifact_service.py](/Users/bytedance/my_project/speak_up/backend/app/services/report_artifact_service.py:11)
- [report_repository.py](/Users/bytedance/my_project/speak_up/backend/app/services/report_repository.py:19)

## 7. 报告页等待态

报告生成期间，前端会先展示 processing 状态，并轮询：

- `GET /api/session/{session_id}/report`

等待态不再使用额外安抚语音。

当前页面会明确提示用户：

- 可以先进入“回放复盘”
- 先查看视频、文字稿和 AI Live Coach 时间线
- 用这段时间缓冲报告生成

## 8. 当前边界

- 存储是本地文件落盘，不是数据库
- 最终报告是一次性生成，不做分块 section streaming
- 报告速度主要取决于 `window pack` 复用率和 `report brain` 模型耗时
- 报告链路不做 QA brief 那种摘要压缩，原始 transcript 和 coach timeline 会保留到最终整合阶段

## 9. 关键文件

- [session_manager.py](../backend/app/services/session_manager.py)
- [report_job_service.py](../backend/app/services/report_job_service.py)
- [report_window_builder_service.py](../backend/app/services/report_window_builder_service.py)
- [report_signal_service.py](../backend/app/services/report_signal_service.py)
- [report_brain_service.py](../backend/app/services/report_brain_service.py)
- [session-provider.tsx](../src/components/session/session-provider.tsx)
