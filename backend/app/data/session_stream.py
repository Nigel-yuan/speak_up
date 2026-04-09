from app.schemas import LiveInsight, SessionStreamFrame, TranscriptChunk


SESSION_STREAMS: dict[str, dict[str, list[SessionStreamFrame]]] = {
    "host": {
        "zh": [
            SessionStreamFrame(
                second=8,
                transcript=TranscriptChunk(
                    id="host-zh-transcript-1",
                    speaker="user",
                    text="大家晚上好，欢迎来到今天的产品发布活动，我是今天的主持人。",
                    timestampLabel="00:08",
                ),
                insight=LiveInsight(
                    id="host-zh-insight-1",
                    title="开场状态自然",
                    detail="你的第一句话语速稳定，镜头注视也比较自然，观众会更容易进入状态。",
                    tone="positive",
                ),
            ),
            SessionStreamFrame(
                second=20,
                transcript=TranscriptChunk(
                    id="host-zh-transcript-2",
                    speaker="user",
                    text="接下来我们会一起聊聊这款产品背后的设计理念，也会邀请嘉宾和大家分享一线经验。",
                    timestampLabel="00:20",
                ),
                insight=LiveInsight(
                    id="host-zh-insight-2",
                    title="信息组织清楚",
                    detail="你把接下来的流程交代得很完整，不过在句尾可以再稍微放慢一点，让重点更清晰。",
                    tone="neutral",
                ),
            ),
            SessionStreamFrame(
                second=34,
                transcript=TranscriptChunk(
                    id="host-zh-transcript-3",
                    speaker="user",
                    text="首先，让我们欢迎今天来到现场的几位嘉宾，也欢迎线上直播间的朋友们。",
                    timestampLabel="00:34",
                ),
                insight=LiveInsight(
                    id="host-zh-insight-3",
                    title="互动感不错",
                    detail="你有在照顾线上线下两边观众，这会让主持的连接感更强。",
                    tone="positive",
                ),
            ),
        ],
        "en": [
            SessionStreamFrame(
                second=8,
                transcript=TranscriptChunk(
                    id="host-en-transcript-1",
                    speaker="user",
                    text="Good evening everyone, and welcome to our product launch event.",
                    timestampLabel="00:08",
                ),
                insight=LiveInsight(
                    id="host-en-insight-1",
                    title="Confident opening",
                    detail="Your first sentence lands clearly and your pace feels steady on camera.",
                    tone="positive",
                ),
            ),
            SessionStreamFrame(
                second=22,
                transcript=TranscriptChunk(
                    id="host-en-transcript-2",
                    speaker="user",
                    text="In the next few minutes, we will walk through the product vision and hear directly from our guests.",
                    timestampLabel="00:22",
                ),
                insight=LiveInsight(
                    id="host-en-insight-2",
                    title="Flow is clear",
                    detail="The structure is easy to follow. Try pausing a touch longer before naming the next segment.",
                    tone="neutral",
                ),
            ),
            SessionStreamFrame(
                second=36,
                transcript=TranscriptChunk(
                    id="host-en-transcript-3",
                    speaker="user",
                    text="Please join me in welcoming our speakers, and a big hello to everyone watching online.",
                    timestampLabel="00:36",
                ),
                insight=LiveInsight(
                    id="host-en-insight-3",
                    title="Audience connection",
                    detail="You acknowledge both in-person and online audiences, which strengthens your host presence.",
                    tone="positive",
                ),
            ),
        ],
    },
    "guest-sharing": {
        "zh": [
            SessionStreamFrame(
                second=10,
                transcript=TranscriptChunk(
                    id="guest-zh-transcript-1",
                    speaker="user",
                    text="今天我想和大家分享的，是我们团队在过去半年里做的三个关键判断。",
                    timestampLabel="00:10",
                ),
                insight=LiveInsight(
                    id="guest-zh-insight-1",
                    title="主旨进入很快",
                    detail="你很快抛出了主题，听众会更容易知道接下来该听什么。",
                    tone="positive",
                ),
            ),
            SessionStreamFrame(
                second=24,
                transcript=TranscriptChunk(
                    id="guest-zh-transcript-2",
                    speaker="user",
                    text="第一个判断是，我们不能只追求功能数量，而要优先解决用户最常遇到的问题。",
                    timestampLabel="00:24",
                ),
                insight=LiveInsight(
                    id="guest-zh-insight-2",
                    title="观点表达清楚",
                    detail="这句话逻辑很顺，不过关键词可以再重读一下，让结论更有力量。",
                    tone="neutral",
                ),
            ),
            SessionStreamFrame(
                second=40,
                transcript=TranscriptChunk(
                    id="guest-zh-transcript-3",
                    speaker="user",
                    text="直到我们重新访谈了二十位核心用户，很多判断才真正发生改变。",
                    timestampLabel="00:40",
                ),
                insight=LiveInsight(
                    id="guest-zh-insight-3",
                    title="故事感建立起来了",
                    detail="这里加入真实动作和数量，会让分享更可信，也更容易打动人。",
                    tone="positive",
                ),
            ),
        ],
        "en": [
            SessionStreamFrame(
                second=10,
                transcript=TranscriptChunk(
                    id="guest-en-transcript-1",
                    speaker="user",
                    text="Today I want to share three decisions that changed how our team builds products.",
                    timestampLabel="00:10",
                ),
                insight=LiveInsight(
                    id="guest-en-insight-1",
                    title="Clear entry point",
                    detail="You establish the topic quickly, which gives the audience a strong frame for the rest of the talk.",
                    tone="positive",
                ),
            ),
            SessionStreamFrame(
                second=26,
                transcript=TranscriptChunk(
                    id="guest-en-transcript-2",
                    speaker="user",
                    text="The first decision was to stop chasing feature count and focus on the most painful user problems.",
                    timestampLabel="00:26",
                ),
                insight=LiveInsight(
                    id="guest-en-insight-2",
                    title="Strong message",
                    detail="The statement is clear. Add a bit more emphasis on the contrast to make it more memorable.",
                    tone="neutral",
                ),
            ),
            SessionStreamFrame(
                second=42,
                transcript=TranscriptChunk(
                    id="guest-en-transcript-3",
                    speaker="user",
                    text="Only after we interviewed twenty core users did our assumptions really begin to shift.",
                    timestampLabel="00:42",
                ),
                insight=LiveInsight(
                    id="guest-en-insight-3",
                    title="Credible detail",
                    detail="Specific numbers make your story feel grounded and persuasive.",
                    tone="positive",
                ),
            ),
        ],
    },
    "standup": {
        "zh": [
            SessionStreamFrame(
                second=9,
                transcript=TranscriptChunk(
                    id="standup-zh-transcript-1",
                    speaker="user",
                    text="我最近发现，成年人最擅长的一件事，就是假装自己一点都不累。",
                    timestampLabel="00:09",
                ),
                insight=LiveInsight(
                    id="standup-zh-insight-1",
                    title="开头有代入感",
                    detail="这个观察很贴近生活，观众比较容易被你带进来。",
                    tone="positive",
                ),
            ),
            SessionStreamFrame(
                second=21,
                transcript=TranscriptChunk(
                    id="standup-zh-transcript-2",
                    speaker="user",
                    text="你白天说没事，晚上回家躺下之后，连手机掉脸上都懒得喊疼。",
                    timestampLabel="00:21",
                ),
                insight=LiveInsight(
                    id="standup-zh-insight-2",
                    title="画面感很强",
                    detail="这句的细节很好，不过包袱后可以多留一点空白，观众会更容易反应。",
                    tone="warning",
                ),
            ),
            SessionStreamFrame(
                second=35,
                transcript=TranscriptChunk(
                    id="standup-zh-transcript-3",
                    speaker="user",
                    text="第二天同事问你状态怎么样，你还得说，挺好的，正在燃烧自己。",
                    timestampLabel="00:35",
                ),
                insight=LiveInsight(
                    id="standup-zh-insight-3",
                    title="反差开始出来了",
                    detail="前后反差表达得不错，再把“燃烧自己”这几个字压重一点会更有记忆点。",
                    tone="positive",
                ),
            ),
        ],
        "en": [
            SessionStreamFrame(
                second=9,
                transcript=TranscriptChunk(
                    id="standup-en-transcript-1",
                    speaker="user",
                    text="I recently realized that adults are incredibly good at pretending they are totally fine.",
                    timestampLabel="00:09",
                ),
                insight=LiveInsight(
                    id="standup-en-insight-1",
                    title="Relatable opening",
                    detail="This is an easy setup for the audience to connect with right away.",
                    tone="positive",
                ),
            ),
            SessionStreamFrame(
                second=23,
                transcript=TranscriptChunk(
                    id="standup-en-transcript-2",
                    speaker="user",
                    text="You say you're okay all day, and then at night your phone falls on your face and you do not even react.",
                    timestampLabel="00:23",
                ),
                insight=LiveInsight(
                    id="standup-en-insight-2",
                    title="Good visual detail",
                    detail="The image is funny. Leave a bit more room after the line so the joke can breathe.",
                    tone="warning",
                ),
            ),
            SessionStreamFrame(
                second=37,
                transcript=TranscriptChunk(
                    id="standup-en-transcript-3",
                    speaker="user",
                    text="Then your coworker asks how you're doing, and you say, thriving, just slowly combusting.",
                    timestampLabel="00:37",
                ),
                insight=LiveInsight(
                    id="standup-en-insight-3",
                    title="Punchline contrast works",
                    detail="The contrast is landing. Put a little more weight on the final phrase for a stronger finish.",
                    tone="positive",
                ),
            ),
        ],
    },
}


def get_session_frames(scenario_id: str, language: str) -> list[SessionStreamFrame]:
    scenario_streams = SESSION_STREAMS.get(scenario_id) or SESSION_STREAMS["host"]
    return scenario_streams.get(language) or scenario_streams["zh"]


def get_session_frames_for_realtime(scenario_id: str, language: str) -> list[SessionStreamFrame]:
    frames = get_session_frames(scenario_id, language)

    if not frames:
        return []

    offset = frames[0].second - 1
    return [frame.model_copy(update={"second": frame.second - offset}) for frame in frames]
