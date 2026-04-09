from app.schemas import ScenarioOption


SCENARIOS: list[ScenarioOption] = [
    ScenarioOption(
        id="host",
        title="主持人场景",
        subtitle="控场、引导、节奏推进",
        description="模拟活动主持、直播串场或会议控场，重点训练开场气场、流程衔接与互动感。",
        goals=["开场自然", "控场稳定", "互动有温度"],
        audience="观众、嘉宾与线上评论区",
        accentColor="#8b5cf6",
    ),
    ScenarioOption(
        id="guest-sharing",
        title="嘉宾分享场景",
        subtitle="观点表达、故事讲述、逻辑递进",
        description="模拟发布会、路演或团队分享，重点训练信息组织、观点表达与感染力。",
        goals=["观点清晰", "故事完整", "表达有说服力"],
        audience="主持人、评委或团队成员",
        accentColor="#0f766e",
    ),
    ScenarioOption(
        id="standup",
        title="脱口秀场景",
        subtitle="节奏、停顿、包袱与现场反馈",
        description="模拟轻喜剧或即兴表达，重点训练笑点铺垫、情绪推进与反应速度。",
        goals=["节奏松弛", "停顿有效", "包袱清晰"],
        audience="现场观众与朋友",
        accentColor="#ea580c",
    ),
]
