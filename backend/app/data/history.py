from app.schemas import HistoricalSessionSummary, MetricDelta, RadarMetric, SessionReport, SuggestionItem


HISTORICAL_SESSIONS: list[HistoricalSessionSummary] = [
    HistoricalSessionSummary(
        id="hist-001",
        label="上周三 · 中文主持",
        scenarioId="host",
        overallScore=76,
        summary="开场自然，但在串联环节上略有停顿，和嘉宾互动时还有进一步放松的空间。",
        deltas=[
            MetricDelta(metric="控场", change=8),
            MetricDelta(metric="互动", change=6),
            MetricDelta(metric="节奏", change=-2),
        ],
    ),
    HistoricalSessionSummary(
        id="hist-002",
        label="上周五 · English sharing",
        scenarioId="guest-sharing",
        overallScore=81,
        summary="观点层次清楚，英文表达稳定，但结尾的号召力还可以更强。",
        deltas=[
            MetricDelta(metric="逻辑", change=7),
            MetricDelta(metric="表达", change=4),
            MetricDelta(metric="收束", change=-1),
        ],
    ),
    HistoricalSessionSummary(
        id="hist-003",
        label="本周一 · 脱口秀试讲",
        scenarioId="standup",
        overallScore=73,
        summary="笑点前的铺垫做得不错，不过包袱落点略快，观众反应空间偏短。",
        deltas=[
            MetricDelta(metric="节奏", change=5),
            MetricDelta(metric="表现力", change=3),
            MetricDelta(metric="停顿", change=-4),
        ],
    ),
]


REPORT_TEMPLATES: dict[str, SessionReport] = {
    "host": SessionReport(
        sessionId="mock-report-host",
        status="ready",
        overallScore=84,
        headline="你已经有很强的主持松弛感",
        encouragement="这一轮里，你的开场状态稳定，能够快速把观众带进节奏，整体呈现比历史记录更从容。",
        summaryParagraph="这轮的主持状态比较稳，控场和镜头亲和力已经有了清晰的优势。",
        highlights=[
            "破冰速度快，前 20 秒就建立了轻松氛围",
            "切换议题时衔接自然，没有明显卡顿",
            "眼神和微笑配合更稳定，镜头亲和力提升明显",
        ],
        suggestions=[
            SuggestionItem(title="放慢提问前半拍", detail="在抛出问题前多留 0.5 秒停顿，可以让嘉宾和观众更好地跟上节奏。"),
            SuggestionItem(title="增强关键词重音", detail="介绍嘉宾或活动亮点时，把关键名词重读，会让信息更有记忆点。"),
            SuggestionItem(title="增加互动追问", detail="你已经能自然控场，下一步可以加入一句简短追问，让现场交流更有层次。"),
        ],
        radarMetrics=[
            RadarMetric(subject="肢体", score=82, fullMark=100),
            RadarMetric(subject="表情", score=85, fullMark=100),
            RadarMetric(subject="语音语调", score=86, fullMark=100),
            RadarMetric(subject="节奏", score=85, fullMark=100),
            RadarMetric(subject="内容质量", score=80, fullMark=100),
            RadarMetric(subject="表达结构", score=83, fullMark=100),
        ],
        generatedAt="2026-04-21T00:00:00Z",
    ),
    "guest-sharing": SessionReport(
        sessionId="mock-report-guest-sharing",
        status="ready",
        overallScore=86,
        headline="你的观点输出已经很有说服力",
        encouragement="这次分享的逻辑骨架清楚，英文切换自然，整体表达成熟度比历史记录更进一步。",
        summaryParagraph="这轮分享最明显的优势是结构清楚、主观点进入快，整体表达已经比较成熟。",
        highlights=[
            "开头快速抛出主结论，信息进入效率高",
            "案例与观点连接顺畅，听众容易跟住你的思路",
            "语气稳定，英文表达时没有明显犹豫",
        ],
        suggestions=[
            SuggestionItem(title="结尾再向上收一层", detail="最后一段可以补一句更有动作感的总结，让分享的收束更有力量。"),
            SuggestionItem(title="拉开重点句的停顿", detail="在结论句后多停顿半秒，有助于让关键观点被真正听见。"),
            SuggestionItem(title="增加观众代入语句", detail="适当使用“你可能也遇到过”这类表达，会让内容更有共鸣。"),
        ],
        radarMetrics=[
            RadarMetric(subject="肢体", score=76, fullMark=100),
            RadarMetric(subject="表情", score=78, fullMark=100),
            RadarMetric(subject="语音语调", score=80, fullMark=100),
            RadarMetric(subject="节奏", score=81, fullMark=100),
            RadarMetric(subject="内容质量", score=86, fullMark=100),
            RadarMetric(subject="表达结构", score=90, fullMark=100),
        ],
        generatedAt="2026-04-21T00:00:00Z",
    ),
    "standup": SessionReport(
        sessionId="mock-report-standup",
        status="ready",
        overallScore=79,
        headline="你的现场表现力已经开始出来了",
        encouragement="这一轮你在语气和节奏上更放得开，包袱前的情绪铺垫比历史记录更自然，已经有明显进步。",
        summaryParagraph="这轮的舞台状态更放开了，节奏和语气已经开始形成自己的现场感。",
        highlights=[
            "表情和肢体更敢放开，舞台感更强",
            "前半段铺垫完整，观众更容易进入你的叙述",
            "几个笑点之间的转场自然，没有生硬断开",
        ],
        suggestions=[
            SuggestionItem(title="包袱后多留一点空白", detail="笑点落下后别急着接下一句，留一点空间更容易吃到观众反馈。"),
            SuggestionItem(title="强化反差词", detail="在 punchline 前把反差词说得更重，会更容易形成记忆点。"),
            SuggestionItem(title="控制语速起伏", detail="你的整体节奏不错，但个别地方冲得偏快，适当拉开会更松弛。"),
        ],
        radarMetrics=[
            RadarMetric(subject="肢体", score=82, fullMark=100),
            RadarMetric(subject="表情", score=84, fullMark=100),
            RadarMetric(subject="语音语调", score=80, fullMark=100),
            RadarMetric(subject="节奏", score=83, fullMark=100),
            RadarMetric(subject="内容质量", score=74, fullMark=100),
            RadarMetric(subject="表达结构", score=76, fullMark=100),
        ],
        generatedAt="2026-04-21T00:00:00Z",
    ),
}


def get_report_by_scenario(scenario_id: str) -> SessionReport:
    return REPORT_TEMPLATES.get(scenario_id, REPORT_TEMPLATES["host"])
