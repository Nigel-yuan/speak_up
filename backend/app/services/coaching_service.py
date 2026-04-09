from app.schemas import LiveInsight, LiveInsightEvent


class MockCoachingService:
    def build_live_insight_event(self, insight: LiveInsight) -> LiveInsightEvent:
        return LiveInsightEvent(insight=insight)
