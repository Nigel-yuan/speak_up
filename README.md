# Speak Up

Speak Up 是一个 AI 演讲训练原型，当前已经把三条实时链路接起来了：

- 实时 ASR
- 实时 AI Live Coach
- AI 问答训练

报告、历史和回放仍然是原型态，但训练主流程已经可用。

## 当前能力

### 训练模式

- `free_speech`
- `document_speech`

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
- 文档当前仍不参与 Live Coach 的实时打分

## 实时链路

### ASR

- 前端通过 `AudioWorklet` 采集麦克风
- 音频重采样到 `PCM 16k mono`
- 后端转发给阿里云 `qwen3-asr-flash-realtime`
- 前端消费 `transcript_partial` / `transcript_final`

### Live Coach

- 视频帧约每秒 1 张
- 后端维持两条 Omni lane：
  - `voice_content`
  - `body_visual`
- Omni patch 和本地 transcript 规则统一汇总成 `coach_panel`

### QA

- `qa_brain_service` 负责压缩上下文和预热 brief
- `qwen3.5-omni-plus-realtime` 负责实时口播提问
- 用户回答期间，ASR partial 会先进入临时答案
- `speech_stopped` 后，如果答案不是空/语气词，`2s` 后自动进入下一轮
- 如果一直没有有效回答，`10s` 静默兜底决定追问、下一题或结束
- 前端会回传 interviewer 音频播放开始/结束，避免服务端在音频还没播完时提前推进

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
- `GET /api/scenarios`
- `GET /api/history`
- `GET /api/report`
- `POST /api/session/start`
- `GET /api/session/{session_id}`
- `POST /api/session/{session_id}/finish`
- `GET /api/session/{session_id}/replay`
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
- `src/components/session/qa-avatar-panel.tsx`
- `src/hooks/useMockSession.ts`

## 当前限制

- 报告页还不是按真实 session 生成
- 历史记录仍然是静态数据
- 回放页还没有真实音视频回放
- 文档当前只参与 QA，不参与 Live Coach 实时评分
