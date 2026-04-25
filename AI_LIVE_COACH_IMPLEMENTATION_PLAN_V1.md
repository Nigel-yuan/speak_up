# Speak Up AI Live Coach Implementation Plan V1

## 文档目的

这份文档回答一个工程问题：

在不推倒当前实时 ASR 和 Omni Coach 链路的前提下，如何把右侧 `AI Live Coach` 从“滚动 insight feed”重构成“固定三维状态面板”。

这份文档只描述实现方案，不直接修改代码。

注：

- 这份文档包含一部分早期 pose 路线的设计背景
- 当前运行时代码已经切到“前端只采集，后端统一做多模态 coach”
- 以 [README.md](README.md) 和 [REALTIME_ARCHITECTURE.md](backend/REALTIME_ARCHITECTURE.md) 为当前实现口径

---

## 一、实施目标

本期只做一件事：

- 把右侧 `AI Live Coach` 落成固定产品面板

本期不做：

- 替换当前实时字幕链路
- 增加语音回复
- 替换所有姿态规则
- 重做报告页

本期要保留的现有链路：

- `qwen3-asr-flash-realtime` 继续做实时字幕
- 前端 `MediaPipe Pose` 继续做高频姿态检测
- `Qwen3.5-Omni-Realtime` 继续做多模态 coach sidecar
- `Pose Debug` / `Omni Debug` 继续保留

一句话：

- 当前已有链路不拆
- 只在它们上面增加一个“维度化聚合层”

---

## 二、当前问题

当前右侧面板的问题不是“模型不够强”，而是“状态模型不对”。

当前实现是：

- `pose-rule` 产出 `LiveInsight`
- `omni-coach` 产出 `LiveInsight`
- 前端把 `LiveInsight[]` 当滚动 feed 展示

这会带来 4 个问题：

1. `Pose` 和 `Omni` 抢同一个主卡片
2. 用户看到的是事件流，不是训练状态
3. 一次误报会直接覆盖主面板
4. Debug 友好，但产品不友好

所以这一版不能继续在 `LiveInsight` 上打补丁，而要加一个新的 UI 主状态。

---

## 三、目标架构

### 目标原则

新的右侧面板只认一个状态源：

- `CoachPanelState`

`CoachPanelState` 由后端统一聚合产生，前端只负责渲染。

### 数据分层

建议把实时 coach 拆成 4 层：

1. 原始信号层
   - ASR transcript
   - pose snapshot
   - Omni response

2. 观察层
   - `PoseObservation`
   - `SpeechObservation`
   - `OmniObservation`

3. 聚合层
   - `CoachPanelState`

4. 展示层
   - 顶部一条重点建议
   - 三张固定维度卡
   - 内部诊断区单独展示

### 新旧共存策略

本期可以先保留 `LiveInsight` 数据结构做静态 mock 和过渡兼容，但训练页主 UI 不再依赖它。

建议：

- `coach_panel` 作为右侧主 UI 的唯一输入
- 旧的 `LiveInsight` 只保留在静态 demo 数据层

---

## 四、固定三维的工程拆分

### 1. 肢体 & 表情

主目标：

- 给用户一个稳定的镜头表现判断

当前主来源：

- 前端 pose
- 后端 pose rule

Omni 在这一维的角色：

- 补充高层解释
- 不直接替代几何判断

本期建议的细粒度指标：

- 入镜稳定性
- 构图是否居中
- 头肩或身体是否歪斜
- 头肩或身体是否稳定
- 手势参与感
- 肢体整体是偏紧还是偏放松
- 表情和眼神互动感

本期工程口径：

- `入镜 / 居中 / 歪斜 / 晃动 / 手势` 由规则层主导
- `紧绷 / 放松 / 互动感` 由 Omni 补充

### 2. 语音语调 & 节奏

主目标：

- 给用户一个稳定的声音表现判断

当前主来源：

- Omni
- ASR 时间轴
- 音频基础统计

本期建议的细粒度指标：

- 吐字清晰度
- 语速
- 断句自然度
- 停顿是否合适
- 重音是否打出来
- 整体起伏
- 情绪状态
- 卡壳或找词感

本期工程口径：

- `语速 / 句长 / 停顿 / 口头禅与填充词` 由规则统计提供底座
- `紧张 / 平 / 有起伏 / 有感染力` 由 Omni 提供高层判断

### 3. 内容 & 表达

主目标：

- 给用户一个稳定的表达质量判断

当前主来源：

- ASR transcript
- Omni

本期建议的细粒度指标：

- 简洁度
- 口头禅与填充词
- 重复和绕圈
- 逻辑结构
- 观点是否明确
- 内容推进是否顺

本期工程口径：

- `口头禅 / 重复 / 句长 / 短时段推进` 由 transcript 规则先算
- `逻辑清晰度 / 观点落点 / 表达效率` 由 Omni 补充

---

## 五、推荐的数据结构

右侧主 UI 不再直接消费 `LiveInsight`，而是消费一个完整面板对象。

建议新增：

```json
{
  "summary": {
    "title": "把头肩位置先定住",
    "detail": "镜头里的上身姿态还不够稳，先把头肩摆正，再继续讲重点句。"
  },
  "dimensions": {
    "body_expression": {
      "status": "adjust_now",
      "headline": "头肩姿态还不够稳",
      "detail": "当前镜头里的上身有些倾斜，交流感会变弱。",
      "updated_at_ms": 1710000000000
    },
    "voice_pacing": {
      "status": "stable",
      "headline": "语速基本正常",
      "detail": "整体节奏没有明显失控，但重点句的起伏还不够。",
      "updated_at_ms": 1710000000000
    },
    "content_expression": {
      "status": "doing_well",
      "headline": "内容主线比较清楚",
      "detail": "这一段没有明显绕圈，听众容易跟住你的主线。",
      "updated_at_ms": 1710000000000
    }
  }
}
```

### 用户侧状态建议

前端建议只认这 4 个用户态标签：

- `doing_well`
- `stable`
- `adjust_now`
- `analyzing`

渲染时映射成：

- `做得好`
- `基本稳定`
- `优先调整`
- `分析中`

注意：

- 内部仍然可以保留 `positive / neutral / warning / insufficient_signal`
- 但不要把内部枚举直接暴露给 UI

---

## 六、推荐的后端实现方式

### 新增一个聚合服务

建议新增：

- `backend/app/services/coach_panel_service.py`

职责：

- 接收来自 pose / ASR / Omni 的观察结果
- 维护每个 session 的三维状态
- 生成新的 `CoachPanelState`
- 决定顶部 summary 应该显示哪一条

### 为什么要单独做一个服务

不要把三维聚合逻辑塞回 `SessionManager`。

原因：

- `SessionManager` 现在已经在负责 websocket、provider fanout、transcript 和 omni 分发
- 再把面板状态机塞进去，会继续膨胀

所以建议：

- `SessionManager` 负责事件编排
- `CoachPanelService` 负责产品状态

### 建议新增的观察对象

不要让聚合服务直接吃原始 provider 文本。

建议先新增三类内部 observation：

1. `PoseObservation`
   - 由 `vision_service.py` 产出
   - 不再只返回 `LiveInsight`
   - 应该返回结构化姿态信号

2. `SpeechObservation`
   - 新增 `speech_analysis_service.py`
   - 基于 transcript chunk 和时间轴统计
   - 产出口头禅与填充词、重复、句长、语速、停顿等结构化信号

3. `OmniObservation`
   - 由 `omni_service.py` 产出
   - 不再只返回单条 title/detail
   - 改成返回维度化 patch

### 推荐的聚合顺序

1. `pose_snapshot` 到达
   - `vision_service` 产出 `PoseObservation`
   - `coach_panel_service` 更新 `body_expression`

2. `transcript_final` 到达
   - `speech_analysis_service` 更新 `SpeechObservation`
   - `coach_panel_service` 更新 `voice_pacing` 和 `content_expression` 的规则基底

3. `OmniObservation` 到达
   - `coach_panel_service` 用 Omni patch 覆盖或补充对应维度

4. 聚合后如有变化
   - 广播新的 `coach_panel` 事件

---

## 七、Omni 的改造方向

当前 `omni_service.py` 的输出是：

```json
{
  "should_emit": true,
  "tone": "warning",
  "title": "镜头稍微回正",
  "detail": "你这段内容很清楚，但身体有点偏离镜头中心，回正后交流感会更自然。"
}
```

这只适合滚动 insight，不适合固定三维卡片。

### 建议改成维度化 patch

建议让 Omni 输出：

```json
{
  "should_emit": true,
  "summary": {
    "priority_dimension": "body_expression",
    "title": "镜头稍微回正",
    "detail": "你这段内容很清楚，但身体有点偏离镜头中心，回正后交流感会更自然。"
  },
  "dimensions": {
    "body_expression": {
      "engine_status": "warning",
      "headline": "镜头交流感偏弱",
      "detail": "你这段身体有点偏离镜头中心，回正后会更自然。"
    },
    "voice_pacing": {
      "engine_status": "neutral",
      "headline": "语气基本稳定",
      "detail": "整体语速没有明显失控，但重点句起伏还可以再拉开。"
    },
    "content_expression": {
      "engine_status": "positive",
      "headline": "内容主线清楚",
      "detail": "这一段表达比较直接，听众容易跟住。"
    }
  }
}
```

### 为什么要让 Omni 直接吐三维 patch

原因有 3 个：

1. 右侧 UI 的目标形态就是三维卡片
2. 如果 Omni 继续只吐单条 insight，后端还要做二次猜测分类
3. 维度化 patch 更适合和规则层融合

### Omni 当前链路继续保留的设置

这部分当前方向不变：

- 持续音频流式输入
- 视频帧约 `1 fps`
- `server_vad`
- 只输出文本
- 不做语音回复

根据阿里云当前官方文档：

- `session.update` 支持 `turn_detection.server_vad`
- `input_image_buffer.append` 建议 `1 张/秒`
- `response.text.delta` / `response.text.done` 支持流式文本输出
- `conversation.item.input_audio_transcription.completed` 可返回输入音频转录，但文档明确说明该转录固定由 `gummy-realtime-v1` 处理，仅供参考  

来源：

- 阿里云客户端事件：https://help.aliyun.com/zh/model-studio/client-events
- 阿里云服务端事件：https://help.aliyun.com/zh/model-studio/server-events
- 阿里云模型价格与免费额度：https://help.aliyun.com/zh/model-studio/model-pricing

### 关于 transcript 是否喂给 Omni

本期建议：

- 先不额外把 ASR transcript 主动写回 Omni

理由：

- 当前 Omni 已经同时收到音频和图片帧
- 当前产品要先解决的是右侧状态面板，不是让 Omni 成为唯一理解中枢
- transcript 已经在本地后端可用于规则统计，没有必要第一步就把上下文同步复杂化

后续如果内容维度不够稳定，再评估把最近 1 到 2 句 transcript 做成补充上下文。

---

## 八、Pose 链路需要同步重构

当前 `vision_service.py` 直接产出用户态 `LiveInsight`，这不适合新的三维卡片。

建议改成两层输出：

1. 内部结构化观察
2. 兼容期 `LiveInsight`

### 推荐新增的 `PoseObservation`

建议包含：

- `camera_mode`
- `body_present`
- `face_visible`
- `shoulder_visible`
- `hip_visible`
- `hands_visible`
- `framing`
- `posture_alignment`
- `stability`
- `gesture_level`
- `body_tension`
- `visual_engagement`
- `engine_status`

### 当前必须一起修的姿态问题

这次重构右侧面板时，必须顺手修掉两个错误入口：

1. `head-only` 不能再落入肩线判断
2. 近景模式不能再轻易触发“站姿”语义

否则新的三维卡片会继续被错误底层信号污染。

---

## 九、新增 transcript 规则分析层

当前内容与节奏维度，不能完全依赖 Omni。

建议新增：

- `backend/app/services/speech_analysis_service.py`

职责：

- 消费 `TranscriptChunk`
- 维护最近几句的短时窗口
- 产出结构化语音/内容统计

建议首批统计：

- `filler_density`：口头禅 / 填充词密度
- `repetition_score`
- `avg_sentence_length`
- `pause_pattern`
- `pace_band`
- `restart_count`
- `content_progression_score`

### 为什么要单独做这层

因为：

- `内容 & 表达` 不能只靠模型生成一句点评
- 报告页后面也会复用这一层
- 这层是后面做“报告与实时一致”的基础

---

## 十、前端改造方案

### 保留不动的部分

本期前端不需要动这些主链路：

- 音频采集
- 视频帧上行
- Pose Debug
- Omni Debug
- 实时字幕

### 主要重构点

1. `src/types/session.ts`
   - 新增 `CoachPanelState`
   - 新增 `CoachDimensionState`
   - 新增 `CoachSummary`
   - `LiveInsight` 仅保留在静态 demo 数据层

2. `src/hooks/useMockSession.ts`
   - 新增 `coachPanel` 状态
   - 监听新的 `coach_panel` websocket 事件
   - 不再要求训练页保留 `currentInsight` / `insights`

3. `src/components/session/live-analysis-panel.tsx`
   - 从“滚动 list + 主卡片”
   - 改成“顶部 summary + 3 张固定维度卡 + 内部诊断区”

### 推荐的前端渲染结构

```text
AI Live Coach
  SummaryCard
  DimensionCard(body_expression)
  DimensionCard(voice_pacing)
  DimensionCard(content_expression)
  DiagnosticsSection(optional)
```

### 过渡期建议

第一版就让主 UI 只显示 `coach_panel`。

如果需要留排障视图：

- 只放到内部诊断区
- 不再作为用户主视图的一部分

---

## 十一、事件与 Schema 设计

### 新增 websocket 事件

建议新增：

```python
RealtimeEventType += "coach_panel"
```

新增事件模型：

```python
class CoachPanelEvent(BaseModel):
    type: Literal["coach_panel"] = "coach_panel"
    coachPanel: CoachPanelState
```

### 后端建议新增的 schema

- `CoachDimensionId`
- `CoachDisplayStatus`
- `CoachSummary`
- `CoachDimensionState`
- `CoachPanelState`

### 为什么不用继续复用 `LiveInsight`

因为 `LiveInsight` 的设计是：

- 单条事件
- 单一 tone
- 单一 title/detail

它无法表达：

- 三维同时存在
- 每个维度独立更新时间
- 顶部 summary 与维度卡分离

所以不能硬复用。

---

## 十二、推荐的落地顺序

### Phase 1：先搭状态骨架

先做：

- 新增 schema
- 新增 `CoachPanelService`
- 新增 `coach_panel` websocket 事件
- 前端固定三维卡骨架

这一阶段可以先用 mock 数据跑通 UI。

### Phase 2：接入 body 维度

把：

- `vision_service.py`

先改成产出 `PoseObservation`，驱动：

- `body_expression`

同时修：

- `head-only` 不做肩线判断

### Phase 3：接入 voice/content 规则层

新增：

- `speech_analysis_service.py`

先把：

- 口头禅与填充词
- 语速
- 停顿
- 重复

接到：

- `voice_pacing`
- `content_expression`

### Phase 4：把 Omni 从单条 insight 升级成维度 patch

修改：

- `omni_service.py`

让它输出：

- `summary`
- `dimensions`

并接进 `CoachPanelService`

### Phase 5：彻底收掉旧 insight feed

最后才做：

- 主 UI 不再依赖 `LiveInsight`
- 旧 insight feed 只保留在静态 demo 数据层或直接删除

---

## 十三、验收标准

这版完成后，训练页右侧应该满足：

1. 不再滚动刷 insight 历史
2. 永远固定展示三张维度卡
3. 维度卡只显示用户态文案
4. `分析中` 不解释底层原因
5. 只露头时，不再出现“肩线倾斜”之类错误判断
6. Omni 即使延迟一两拍，也不会把整个主面板打回事件流
7. Debug 打开时，仍然能看到 Pose/Omni 的原始调试信息

---

## 十四、最终建议

这一版实现的关键不是“让 Omni 说更多”，而是：

- 让后端先拥有一个稳定的 `CoachPanelState`
- 让前端只负责渲染这个状态

所以最稳的工程路径是：

1. 先建聚合层
2. 再把 Pose / Transcript / Omni 接进去
3. 最后再去清理旧的 `LiveInsight` 事件流

不要反过来做。
