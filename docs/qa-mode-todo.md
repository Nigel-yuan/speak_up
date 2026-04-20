# QA 模式待跟进项

这份清单只保留当前仍然有价值的后续项。

## 1. Brain 超时后的体验

- 现状：`qa.brain.prepare_pack_failed` 超时后，会退回缓存 brief 或 fallback brief，QA 不会中断。
- 后续：可以把 timeout 和 fallback 命中率做成更明确的指标，而不是只看日志。

## 2. 文档能力边界

- 现状：QA 已使用文档文本，但 Live Coach 还不使用文档内容。
- 后续：如果要做“按文档评分”，建议单独设计，不要直接塞进现有 coach lane。

## 3. 追问质量

- 现状：追问判定主要依赖回答长度、关键点命中和轮次上限。
- 后续：可以补一个更稳定的“回答是否真正覆盖问题目标”的判定层。

## 4. 回放与复盘

- 现状：QA 音频已落盘，可通过 `/api/session/{session_id}/qa/turns/{turn_id}/audio` 取回。
- 后续：把 turn 级音频、文本和反馈串成可回放的 QA timeline。
