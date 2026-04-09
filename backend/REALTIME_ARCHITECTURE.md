# 实时视频处理 / 语音转文字接入方案

## 目标
在当前 `Speak Up` 的 FastAPI mock 后端上，逐步从静态 REST mock 演进到“实时会话 + 流式转写 + 实时反馈 + 结束后生成报告”的架构，同时尽量复用现有前端页面与数据模型。

---

## 总体架构

```mermaid
flowchart LR
    A[Browser 前端\nCamera + Mic + UI] -->|POST /api/session/start| B[FastAPI Session API]
    A <-->|WS /ws/session/{session_id}| C[FastAPI Realtime Gateway]
    C --> D[Session Manager]
    D --> E[STT Service]
    D --> F[Vision Service]
    D --> G[Coaching Service]
    D --> H[(Session Store / History / Report)]
    B --> D
    D -->|GET /api/report| H
```

### 职责拆分
- **REST 控制面**
  - 会话开始/结束
  - 场景、历史、报告查询
- **WebSocket 实时面**
  - 接收音频 chunk / 视频帧 / 控制事件
  - 回推 partial transcript / final transcript / live insight / status
- **Session Manager**
  - 管单次训练会话状态
  - 聚合 transcript、视觉观察、反馈事件
- **STT Service**
  - 统一封装语音转文字供应商
- **Vision Service**
  - 先做 mock，后续接真实帧分析
- **Coaching Service**
  - 结合 transcript + 视觉信号产出实时 coaching

---

## 为什么这样设计

### 不建议直接上传整段视频
浏览器实时训练场景里，整段视频直传后端的问题很多：
- 带宽和成本高
- 延迟不可控
- 服务端解码压力大
- 对原型迭代不友好

### 更推荐的数据流
- **音频**：持续切块上传，供 STT 使用
- **视频**：低频抽帧上传，供视觉分析使用
- **后端**：聚合成实时 transcript / insight
- **结束后**：生成整场 report

---

## Phase 路线

## Phase 1：假实时协议打通（本次先实现）
### 目标
先把实时协议、会话生命周期、后端事件推送打通，不接真实 STT / 视频分析。

### 能力
- `POST /api/session/start`
- `POST /api/session/{session_id}/finish`
- `GET /api/session/{session_id}`
- `WebSocket /ws/session/{session_id}`
- 前端或测试客户端可发送：
  - `ping`
  - `start_stream`
  - `audio_chunk`（先只接收，不做真实识别）
  - `video_frame`（先只接收，不做真实分析）
- 后端按 mock timeline 主动回推：
  - `session_status`
  - `transcript_final`
  - `live_insight`

### 价值
- 前后端协议先定下来
- 后续换真实 STT / 视觉时，不用重做整体架构

---

## Phase 2：接入真实 STT
### 目标
把音频 chunk 接到真实 ASR，产生 partial / final transcript。

### 技术方案
- 浏览器录音切块：300ms ~ 1000ms
- 后端 `stt_service.py` 封装厂商 SDK / API
- WebSocket 回推：
  - `transcript_partial`
  - `transcript_final`

### 推荐供应商
- 先快接：Deepgram / AssemblyAI / OpenAI Realtime
- 想自托管：faster-whisper

---

## Phase 3：接入视频帧分析
### 目标
让 live insight 不只依赖 transcript，也能看用户镜头状态。

### 技术方案
- 前端每秒抽帧 1~2 次
- 后端 `vision_service.py` 分析：
  - 视线稳定性
  - 低头时长
  - 表情/头部运动
  - 镜头存在性
- `coaching_service.py` 把视觉信号 + transcript 合并生成反馈

### 第一选择
- OpenCV / MediaPipe 做轻量视觉特征
- 暂不直接上重型视频大模型

---

## Phase 4：结束后真实生成报告
### 目标
会话结束后不再直接读固定 mock report，而是根据整场内容动态生成。

### 技术方案
- 汇总：
  - transcript 全量文本
  - 时间轴事件
  - 视觉统计指标
- 生成：
  - overallScore
  - radarMetrics
  - suggestions
  - comparisonSummary
- 落库 / 写存储
- `GET /api/report` 改为读取真实 session/report 数据

---

## WebSocket 协议建议

### 前端 -> 后端
```json
{ "type": "ping" }
```

```json
{ "type": "start_stream" }
```

```json
{
  "type": "audio_chunk",
  "timestamp_ms": 1200,
  "payload": "<base64 or binary>"
}
```

```json
{
  "type": "video_frame",
  "timestamp_ms": 1400,
  "image_base64": "..."
}
```

### 后端 -> 前端
```json
{
  "type": "session_status",
  "status": "streaming"
}
```

```json
{
  "type": "transcript_partial",
  "text": "大家晚上好，欢迎来到..."
}
```

```json
{
  "type": "transcript_final",
  "chunk": {
    "id": "tx-12",
    "speaker": "user",
    "text": "大家晚上好，欢迎来到今天的活动现场。",
    "timestampLabel": "00:12"
  }
}
```

```json
{
  "type": "live_insight",
  "insight": {
    "id": "ins-5",
    "title": "眼神交流稳定",
    "detail": "你刚刚的镜头注视更自然，表达可信度更高。",
    "tone": "positive"
  }
}
```

---

## 后端目录演进建议

```text
backend/
  app/
    main.py
    schemas.py
    routers/
      session.py
      report.py
    services/
      session_manager.py
      stt_service.py
      vision_service.py
      coaching_service.py
    data/
      scenarios.py
      history.py
      session_stream.py
```

### 说明
- **Phase 1** 可以先不拆 router 很细，但 service 层应先立起来
- `stt_service.py` / `vision_service.py` 第一版可先保留 mock 实现
- `session_manager.py` 是后面最核心的状态聚合层

---

## 推荐落地顺序
1. Phase 1：打通 realtime session 协议与 mock 推流
2. Phase 2：把 audio_chunk 接入真实 STT
3. Phase 3：把 video_frame 接入轻量视觉分析
4. Phase 4：结束后生成真实 report 并存历史

---

## 当前实现策略
本轮先实现 **Phase 1**：
- 补 session start/finish/get
- 补 websocket realtime channel
- 后端从现有 mock `session_stream` 数据里按秒推送 transcript/insight
- 先让整个实时协议跑起来，便于后面替换成真 STT / 真视频分析
