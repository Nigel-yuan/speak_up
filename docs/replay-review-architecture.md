# 回放复盘架构

这份文档只描述当前仓库已经落地的“回放复盘”实现。

## 1. 目标

回放复盘页的目标是把这次训练里的三类信息放到同一个时间坐标下：

- 媒体回放
- 同步文字稿
- AI Live Coach 建议

当前交互原则只有一条：

**以媒体时间为唯一主时钟，让视频、文字稿和 coach 建议保持联动。**

## 2. 当前实现

### 页面入口

- 报告页右上角提供“回放复盘”按钮
- 路由为 `src/app/session/[sessionId]/replay/page.tsx`
- 从回放页返回报告时，会带回 `sessionId / scenario / coach`，避免误跳首页或丢失教练身份

### 页面结构

当前页面采用双栏布局：

- 左侧：放大的媒体播放器
- 右侧：按时间排序的同步复盘列表

底部全局时间轴已经移除，不再维护第三套同步控件。

### 同步复盘列表

复盘列表不是把“文字稿”和“建议”分成两个区域，而是按时间顺序混排：

- `transcript`
- `coach insight`

这样用户点击任意一条内容，都可以直接把媒体跳到对应时间点。

## 3. 数据来源

### 3.1 媒体文件

训练页开始时，前端会先获取一条页面级摄像头流。训练过程中的 UI 布局可以在普通演讲和 QA 模式之间切换，但录制始终使用同一条摄像头视频轨，避免组件卸载导致视频轨中途结束。

训练页结束时，前端会先把录制好的媒体 `Blob` 缓存在全局 `SessionProvider`，回放页优先播放这份本地缓存。随后再后台上传到后端做持久化。

当前录制内容包括：

- 摄像头视频轨
- 混合音轨：用户麦克风输入 + QA 模式下 AI 教练的流式提问音频

后端会把文件落到：

- `output/report_data/<session_id>/replay_media.*`

并额外写入：

- `output/report_data/<session_id>/replay_media.json`

### 3.2 文字稿

回放页使用训练时已经沉淀下来的 transcript chunk：

- `startMs`
- `endMs`
- `text`
- `timestampLabel`

这些数据来自报告 artifact，而不是回放页临时拼装。

### 3.3 AI Live Coach 建议

回放页里的 coach 时间线来自报告侧已经落盘的 `coach_signal`。

后端会把原始 signal 整理成更适合复盘阅读的 `ReplayCoachInsight`：

- `startMs / endMs`
- `dimensionId / subDimensionId`
- `severity / polarity`
- `title / message / evidenceText`

相邻且内容重复的 signal 会合并成一条更长的 insight，避免时间线过碎。

## 4. 接口

当前 replay 链路有三条接口：

- `GET /api/session/{session_id}/replay`
- `POST /api/session/{session_id}/replay/media`
- `GET /api/session/{session_id}/replay/media`

其中：

- `POST /replay/media` 负责上传训练结束后的媒体文件
- `GET /replay` 返回页面渲染所需的结构化数据
- `GET /replay/media` 负责真实音视频播放

如果当前浏览器会话里还有本地缓存，回放页会优先使用缓存的 `blob:` URL；刷新页面或重新进入历史会话时，再回退到后端媒体接口。

## 5. SessionReplay 结构

当前回放页真正依赖的数据字段是：

```ts
interface SessionReplay {
  sessionId: string;
  scenarioId: ScenarioType;
  language: LanguageOption;
  coachProfileId: CoachProfileId | null;
  mediaUrl: string | null;
  mediaType: "audio" | "video" | null;
  durationMs: number;
  transcript: TranscriptChunk[];
  coachInsights: ReplayCoachInsight[];
}
```

前端会把 `transcript + coachInsights` 合并成统一时间线后渲染，不再单独维护后端 `timeline` 字段。

## 6. 同步规则

当前同步逻辑如下：

1. 左侧媒体播放时，`timeupdate` 持续更新 `currentTimeMs`
2. 同步复盘列表根据 `currentTimeMs` 计算当前高亮项
3. 当前高亮项会自动滚到可视区域
4. 点击任意 transcript 或 coach 卡片，会直接 seek 到对应时间点

所以现在的联动是：

- 媒体驱动时间
- 时间驱动复盘列表高亮
- 复盘列表点击反向驱动媒体 seek

## 7. 后端职责

后端由 `backend/app/services/replay_service.py` 负责 replay 聚合，职责包括：

1. 读取 session 状态
2. 读取 transcript artifact
3. 读取 coach signal artifact
4. 读取媒体文件及元信息
5. 组装 `SessionReplay`

回放数据已经是落盘读取，不是纯内存拼装。

## 8. 前端职责

前端回放页负责三件事：

1. 拉取 replay 数据
2. 维护当前播放时间
3. 渲染媒体和同步复盘列表

当前没有再额外拆成 `replay-player`、`replay-timeline-slider` 等独立组件，而是先集中在单页里实现，保持结构简单。

## 9. 当前边界

- 回放文件当前保存在本地文件系统，不是对象存储
- 当前不做服务端转码，直接回放浏览器录制结果
- 当前只支持单个媒体文件回放，不支持多轨编辑
- 当前视频画面录的是用户摄像头，不是整页 UI 合成画面；QA 环节会保留用户画面和 AI 教练声音
- 当前同步复盘列表以 transcript 和 coach insight 为主，不额外展示波形或逐帧视觉标注

## 10. 关键文件

- `backend/app/services/replay_service.py`
- `backend/app/main.py`
- `src/components/session/session-workspace.tsx`
- `src/components/session/session-stage.tsx`
- `src/components/session/camera-panel.tsx`
- `src/hooks/useMockSession.ts`
- `src/app/session/[sessionId]/replay/page.tsx`
