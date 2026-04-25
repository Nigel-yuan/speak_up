# Speak Up

Speak Up 是一个 AI 演讲训练原型，当前已经把三条实时链路接起来了：

- 实时 ASR
- 实时 AI Live Coach
- AI 问答训练
- 训练报告
- 回放复盘

历史演讲和场景切换入口已下线，当前默认进入通用表达训练。

## 当前能力

### 训练模式

- `free_speech`
- `document_speech`
- 场景不再暴露给用户选择，默认使用 `general`
- 语言入口不再暴露给用户，默认中文

### AI 教练

- 进入训练前先选择 AI 教练
- 主训练页右侧顶部展示当前教练
- QA、报告和回放沿用同一位教练
- QA 语音由教练 profile 驱动，前端不再提供 voice profile 选择器

### 问答模式

- QA 是独立开关，不是第三种训练模式
- 可同时工作在自由演讲和文档演讲下
- 每轮最多 `3` 个主题
- 每个主题最多 `3` 次追问

### 文档输入

- 支持上传 `pdf`
- 支持上传 `md`
- `ppt/pptx` 已下线
- 文档文本会进入 QA 预热和提问上下文
- PDF 和 Markdown 预览共用 `DocumentAssetPreview`，Markdown 在白色文档卡片内部滚动
- 文档当前仍不参与 Live Coach 的实时打分

## 实时链路

### ASR

- 前端通过 `AudioWorklet` 采集麦克风，并请求浏览器启用回声消除、降噪、自动增益
- 音频重采样到 `PCM 16k mono`
- 送后端前会先经过主讲人能量门控：动态跟踪当前最强近场人声，低于阈值的片段转成等长静音，减少旁路噪声触发 ASR / QA
- 后端转发给阿里云 `qwen3-asr-flash-realtime`
- 前端消费 `transcript_partial` / `transcript_final`

### Live Coach

- 视频帧约每秒 1 张
- 后端维持两条 Omni lane：
  - `voice_content`
  - `body_visual`
- Omni patch 和本地 transcript 规则统一汇总成 `coach_panel`

### 报告与回放

- 训练结束后生成真实 `sessionId` 报告
- 报告生成期间，页面只保留必要等待提示，用户可从右上角先进入回放复盘
- 回放复盘播放训练录制媒体，并把文字稿和 AI Live Coach 建议按时间线联动
- 录制媒体包含用户摄像头画面、麦克风音轨，以及 QA 环节 AI 教练口播音频

### QA

- `qa_brain_service` 负责压缩上下文和预热 brief
- `qwen3.5-omni-plus-realtime` 负责实时口播提问
- 用户回答期间，ASR partial 会先进入临时答案
- `speech_stopped` / final transcript 后，如果答案不是空、语气词或过短内容，`2s` 后自动进入下一轮
- partial transcript 只走稳定窗口，默认连续稳定约 `4.5s` 才允许推进，避免用户还没说完就被打断
- “我说完了 / 就这么多 / 以上”等结束口令会走快速提交路径，默认 `350ms` 后进入下一轮
- 如果一直没有有效回答，`10s` 静默兜底决定追问、下一题或结束
- 前端会回传 interviewer 音频播放开始/结束，避免服务端在音频还没播完时提前推进
- 当前主讲人过滤仍是能量门控，不是声纹分离；多人同声或背景人声更大时，下一步需要补主讲人声纹门控

更细的时序和日志说明见 [docs/qa-mode-design.md](docs/qa-mode-design.md)。

## 本地运行

### 环境要求

- Node.js 20+
- npm
- Python 3.11+

### 前端

```bash
npm install
cp .env.example .env.local
npm run dev
```

默认地址：

```text
http://localhost:3000
```

### 后端

```bash
python3 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
backend/.venv/bin/uvicorn app.main:app --reload --app-dir backend --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

## 环境变量

最少需要：

```bash
DASHSCOPE_API_KEY=sk-xxx
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

完整示例见 [.env.example](.env.example)。

## 关键接口

### HTTP

- `GET /health`
- `POST /api/session/start`
- `GET /api/session/{session_id}`
- `POST /api/session/{session_id}/finish`
- `GET /api/session/{session_id}/report`
- `POST /api/session/{session_id}/report/generate`
- `GET /api/session/{session_id}/replay`
- `POST /api/session/{session_id}/replay/media`
- `GET /api/session/{session_id}/replay/media`
- `POST /api/document/extract`
- `GET /api/qa/voice-profiles`
- `GET /api/session/{session_id}/qa/turns/{turn_id}/audio`

### WebSocket

- `WS /ws/session/{session_id}`

前端会发送：

- `start_stream`
- `audio_chunk`
- `video_frame`
- `start_qa`
- `stop_qa`
- `qa_prewarm_context`
- `qa_select_voice_profile`
- `qa_audio_playback_started`
- `qa_audio_playback_ended`

后端会返回：

- `session_status`
- `transcript_partial`
- `transcript_final`
- `coach_panel`
- `qa_state`
- `qa_question`
- `qa_audio_stream_start`
- `qa_audio_stream_delta`
- `qa_audio_stream_end`
- `qa_feedback`
- `qa_voice_profiles`
- `pong`
- `error`

## 目录

```text
src/
  components/session/
  hooks/
  lib/
  types/

backend/app/
  main.py
  schemas.py
  services/
```

QA 相关核心文件：

- `backend/app/services/session_manager.py`
- `backend/app/services/qa_mode_orchestrator.py`
- `backend/app/services/qa_brain_service.py`
- `backend/app/services/qa_omni_realtime_service.py`
- `src/components/session/session-workspace.tsx`
- `src/components/session/session-stage.tsx`
- `src/components/session/document-viewer.tsx`
- `src/components/session/qa-avatar-panel.tsx`
- `src/hooks/useMockSession.ts`

## 当前限制

- 文档当前只参与 QA，不参与 Live Coach 实时评分
