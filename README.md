# Speak Up

Speak Up 是一个 AI 演讲训练原型，目标是把一轮训练拆成「实时演讲 + 即时反馈 + 结束后复盘」的完整闭环。

当前这版已经包含：

- Next.js 16 + React 19 的前端训练页与报告页
- FastAPI mock 后端
- `POST /api/session/start` + `WS /ws/session/{session_id}` 的 realtime session 通道
- 浏览器麦克风音频分片上传与摄像头抽帧调试
- mock transcript / live insight 实时回推
- 静态 mock 报告与历史记录展示

## Tech Stack

- Frontend: Next.js 16, React 19, TypeScript, Tailwind CSS 4
- Backend: FastAPI, Pydantic 2
- Realtime: WebSocket + browser `MediaRecorder`

## Repo Structure

```text
.
├── src/
│   ├── app/                  # Next.js routes
│   ├── components/           # session / report / ui components
│   ├── hooks/                # realtime session hook
│   ├── lib/                  # frontend API client
│   └── types/                # shared frontend types
├── backend/
│   ├── app/
│   │   ├── data/             # mock scenarios / report / stream data
│   │   ├── services/         # session manager / debug store / mock services
│   │   ├── main.py           # FastAPI entry
│   │   └── schemas.py
│   ├── REALTIME_ARCHITECTURE.md
│   └── requirements.txt
├── AGENTS.md
└── README.md
```

## Local Development

### 1. Frontend

```bash
npm install
npm run dev
```

默认前端地址：`http://localhost:3000`

### 2. Backend

```bash
python3 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
uvicorn app.main:app --reload --app-dir backend --port 8000
```

默认后端地址：`http://127.0.0.1:8000`

### 3. Frontend Environment

根目录提供了 `.env.example`：

```bash
cp .env.example .env.local
```

默认值：

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

## Current Product Flow

1. 打开训练页，选择场景与语言
2. 点击开始，前端创建 realtime session
3. 浏览器持续发送音频 chunk 和视频帧到后端
4. 后端回推 mock transcript / insight
5. 点击结束后跳转报告页，当前报告仍然来自 mock 数据

## Debug Output

- 后端调试产物默认写到 `backend/debug/<session_id>/`
- 该目录已加入 `.gitignore`，不会进入仓库
- 当前 realtime 设计说明见 `backend/REALTIME_ARCHITECTURE.md`

## Current Status

这版仓库更接近「realtime 协议与调试链路已打通」的开发阶段，而不是完整产品版：

- realtime transcript / insight 仍然是 mock 推流
- 报告仍然是静态模板
- debug 音频链路正在继续完善

## Useful Commands

```bash
npm run dev
npm run lint
```
