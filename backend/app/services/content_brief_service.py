from app.schemas import LanguageOption, ScenarioType, TrainingMode
from app.services.content_source_service import ReferenceBundle
from app.services.qa_brain_service import AliyunQABrainService, ReferenceBrief


class ContentBriefService:
    def __init__(self, qa_brain_service: AliyunQABrainService) -> None:
        self.qa_brain_service = qa_brain_service

    async def build_reference_brief(
        self,
        *,
        scenario_id: ScenarioType,
        language: LanguageOption,
        training_mode: TrainingMode,
        bundle: ReferenceBundle,
    ) -> ReferenceBrief:
        return await self.qa_brain_service.build_reference_brief(
            scenario_id=scenario_id,
            language=language,
            training_mode=training_mode,
            bundle=bundle,
        )
