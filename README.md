# Speak Up

Speak Up 是一个 AI 演讲训练产品原型。当前这版已经跑通了三条主链路：

- 实时语音转写
- 实时 AI Live Coach
- 训练后报告与回放入口

这不是完整生产系统，但已经不是纯 mock demo。当前形态是：

- 真实实时 ASR：阿里云 `qwen3-asr-flash-realtime`
- 真实实时 Live Coach：阿里云 `Qwen3.5-Omni-Realtime`
- 报告、历史、趋势：仍然是原型数据

## 当前支持

### 训练模式

- 自由演讲
- 文档演讲 V1

### 演讲场景

- `host`
- `guest-sharing`
- `standup`

### 语言

- `zh`
- `en`

### 训练页

- 麦克风采集
- 摄像头预览
- 实时文字稿
- 固定三维 `AI Live Coach`
- 历史记录侧栏
- `开始 / 暂停 / 重置 / 结束并生成报告`

### 文档演讲模式 V1

当前第一版只做前端演讲辅助，不把文档接进实时评分。

已支持：

- 本地上传 `pdf`
- 本地上传 `md`
- 主视区显示文档
- 右上角悬浮视频小窗

当前还没做：

- 文档内容参与实时 AI Live Coach
- 文档内容参与实时评分
- 文档内容参与报告生成

## 当前真实链路

### 实时语音转写

- 前端通过 `AudioWorklet` 采集麦克风
- 重采样到 `PCM 16k mono`
- 约 `100ms` 一包通过 WebSocket 发给后端
- 后端转发给阿里云 `qwen3-asr-flash-realtime`
- 前端消费 `transcript_partial` 和 `transcript_final`

### AI Live Coach

- 前端约 `1s` 发送一张 JPEG 视频帧
- 后端并行维护两条 Omni coach lane：
  - `voice_content`
  - `body_visual`
- 后端把 Omni patch 和 transcript 规则分析统一聚合成 `coach_panel`
- 前端右侧固定展示：
  - `肢体 & 表情`
  - `语音语调 & 节奏`
  - `内容 & 表达`

### 报告与回放

- 报告页目前还是静态原型数据
- 回放页当前以 transcript timeline 为主
- 真实媒体回放链路暂未接入

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

前端环境变量：

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

### 后端

首次启动：

```bash
python3 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
```

在仓库根目录启动：

```bash
backend/.venv/bin/uvicorn app.main:app --reload --app-dir backend --port 8000
```

或在 `backend/` 目录启动：

```bash
cd backend
.venv/bin/uvicorn app.main:app --reload --port 8000
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

常用可选项：

```bash
ALIYUN_REALTIME_ASR_MODEL=qwen3-asr-flash-realtime
ALIYUN_REALTIME_ASR_URL=wss://dashscope.aliyuncs.com/api-ws/v1/realtime

ALIYUN_OMNI_COACH_ENABLED=true
ALIYUN_OMNI_COACH_MODEL=qwen3.5-omni-flash-realtime
ALIYUN_OMNI_COACH_URL=wss://dashscope.aliyuncs.com/api-ws/v1/realtime
ALIYUN_OMNI_COACH_SILENCE_DURATION_MS=2000
ALIYUN_OMNI_BODY_TRIGGER_INTERVAL_MS=1500
```

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

### WebSocket

- `WS /ws/session/{session_id}`

前端会发送：

- `start_stream`
- `audio_chunk`
- `video_frame`
- `ping`

后端会返回：

- `session_status`
- `transcript_partial`
- `transcript_final`
- `coach_panel`
- `pong`
- `error`

## 页面结构

### 训练页

- 左侧：主视区
  - 自由演讲：视频主视区
  - 文档演讲：文档主视区 + 右上角视频小窗
- 右侧上半：`Live Transcript`
- 右侧下半：`AI Live Coach`

### AI Live Coach

- 顶部：当前重点
- 下方：三张固定维度卡
- 不再使用滚动提示流

## 当前限制

- 报告页还不是按真实 session 生成
- 历史记录仍然是静态数据
- 回放页还没有真实视频/音频回放
- 文档模式当前只做前端预览，不参与实时评分
- 问答模式还未接入

## 目录说明

```text
src/
  app/
  components/
  hooks/
  lib/
  types/

backend/
  app/
    data/
    services/
    main.py
  requirements.txt
```

当前核心后端服务：

- `stt_service.py`：实时 ASR
- `omni_service.py`：Omni coach
- `speech_analysis_service.py`：基于 transcript 的规则分析
- `coach_panel_service.py`：统一聚合三维 `coach_panel`
- `session_manager.py`：session 编排与 fanout

## 当前最值得继续做的事

1. 报告页改成按真实 `sessionId` 生成
2. 文档模式接入报告生成
3. 问答模式
4. 真实媒体回放
5. 数据持久化
