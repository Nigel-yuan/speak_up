# QA 模式实现说明

这份文档只描述当前仓库已经落地的实现，不再保留前期大方案。

## 1. 模式定义

- `TrainingMode` 只有两个值：
  - `free_speech`
  - `document_speech`
- QA 是独立开关，不是第三种训练模式。
- 文档模式当前只支持 `pdf` 和 `md`，`ppt/pptx` 已移除。

## 2. 关键文件

### 后端

- `backend/app/services/session_manager.py`
  - WebSocket 编排
  - ASR / Live Coach / QA 三条链路汇总
  - QA 自动推进、静默兜底、音频播放确认
- `backend/app/services/qa_mode_orchestrator.py`
  - QA 状态机
  - 追问 / 下一题 / 结束判定
  - brief 与 focus 管理
- `backend/app/services/qa_brain_service.py`
  - 内容压缩
  - question pack / brief 生成
- `backend/app/services/qa_omni_realtime_service.py`
  - interviewer 实时语音与文本输出
- `backend/app/services/content_source_service.py`
  - 文档、手输文本、transcript 汇总成上下文

### 前端

- `src/components/session/session-workspace.tsx`
  - 训练页主容器
  - QA 开关、文档上传、voice profile
- `src/components/session/session-stage.tsx`
  - 自由演讲 / 文档演讲 / QA 分屏舞台
- `src/components/session/qa-avatar-panel.tsx`
  - interviewer 头像、问题、音频播放
- `src/hooks/useMockSession.ts`
  - WebSocket 客户端
  - 麦克风采集
  - QA 音频流播放和播放状态回传

## 3. 运行时流程

### 3.1 进入训练

1. 前端发送 `start_stream`
2. 后端连接：
   - ASR `qwen3-asr-flash-realtime`
   - Live Coach Omni
3. `session_manager` 同时启动 QA prewarm sidecar
4. prewarm 周期性刷新 `ReferenceBrief`

### 3.2 进入 QA

1. 前端发送 `start_qa`
2. `qa_mode_orchestrator.prepare_start_qa()` 初始化状态
3. 后端连接 `qwen3.5-omni-plus-realtime`
4. 用 prewarm brief 构造 realtime instructions
5. bootstrap 第一问

### 3.3 AI 提问

1. Omni 返回文本和音频流
2. 前端边播边显示问题
3. 前端回传：
   - `qa_audio_playback_started`
   - `qa_audio_playback_ended`
4. 服务端只有在音频播完后才真正打开回答窗口

### 3.4 用户回答

1. 用户音频继续走 ASR
2. partial transcript 先写入 `current_live_partial_answer`
3. final transcript 再落到 `current_answer_chunks`
4. `speech_started` / `speech_stopped` 由 STT provider event 驱动

### 3.5 自动推进

- 如果 `speech_stopped` 后当前答案不是空/语气词：
  - 直接进入 `QA_AUTO_ADVANCE_DELAY_MS`
  - 当前默认是 `2000ms`
- 如果长时间没有有效回答：
  - 进入 `QA_SILENCE_FALLBACK_DELAY_MS`
  - 当前默认是 `10000ms`

## 4. 判题与跳转规则

### 4.1 追问

会优先追问的情况：

- 当前题还没到追问上限
- 回答太短
- 关键点命中不足
- 静默超时且当前题还允许继续追问

### 4.2 下一题

进入下一题的情况：

- 当前回答已有基本内容
- 当前题追问上限已到
- 或静默超时后当前题已无法继续追问

### 4.3 结束

结束条件：

- 已到最后一个主题
- 且最后一个主题也达到轮次上限

当前默认：

- 最多 `3` 个主题
- 每个主题最多 `3` 次追问

## 5. 文档模式如何参与 QA

- 上传 `pdf` / `md` 后，前端先调用 `/api/document/extract`
- 提取出的纯文本进入 `document_text`
- `content_source_service` 会把：
  - 文档文本
  - 手输文本
  - 用户历史 transcript
  合成一份 QA 上下文
- 这份上下文用于：
  - prewarm brief
  - realtime instructions
  - follow-up focus

注意：

- 文档当前只参与 QA
- Live Coach 仍然只看实时音视频与 transcript

## 6. 关键日志

建议重点看这些日志：

- `qa.prewarm.begin / done / skip`
- `qa.realtime.instructions_updated`
- `qa.realtime.turn_started`
- `qa.asr.speech_started / speech_stopped`
- `qa.auto_advance.schedule / fire / cancel`
- `qa.silence_fallback.schedule / fire / cancel`
- `qa.audio_playback.started / ended`
- `qa.realtime.user_turn_committed`

## 7. 当前默认参数

见 `.env.example`，QA 相关默认值如下：

- `QA_PREWARM_INTERVAL_SECONDS=20`
- `QA_PREWARM_TRIGGER_DELAY_MS=1500`
- `QA_AUTO_ADVANCE_DELAY_MS=2000`
- `QA_RESPONSE_DONE_AUDIO_GRACE_MS=1200`
- `QA_SILENCE_FALLBACK_DELAY_MS=10000`
- `QA_MAX_QUESTION_TOPICS=3`
- `QA_MAX_FOLLOW_UPS_PER_QUESTION=3`
