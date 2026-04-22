from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.schemas import LanguageOption, ScenarioType
from app.services.qa_omni_realtime_service import AliyunQAOmniRealtimeService
from app.services.voice_profile_service import VoiceProfileService


logger = logging.getLogger("speak_up.session")


@dataclass(frozen=True)
class ReportReassuranceAudio:
    text: str
    audio_url: str
    duration_ms: int
    voice_profile_id: str


class ReportReassuranceService:
    def __init__(
        self,
        *,
        omni_service: AliyunQAOmniRealtimeService | None = None,
        voice_profile_service: VoiceProfileService | None = None,
    ) -> None:
        self.omni_service = omni_service or AliyunQAOmniRealtimeService()
        self.voice_profile_service = voice_profile_service or VoiceProfileService()
        self.timeout_seconds = max(4.0, min(20.0, float(os.getenv("REPORT_REASSURANCE_AUDIO_TIMEOUT_SECONDS", "12"))))

    async def synthesize(
        self,
        *,
        session_id: str,
        scenario_id: ScenarioType,
        language: LanguageOption,
        attempt_index: int = 0,
        voice_profile_id: str | None = None,
    ) -> ReportReassuranceAudio:
        if not self.omni_service.is_configured:
            raise RuntimeError("Omni Realtime 未配置，无法生成报告等待安抚语音")

        profile = self.voice_profile_service.get(voice_profile_id or "female_gentle_01")
        text = self._build_reassurance_text(language, attempt_index)
        instructions = self._build_instructions(language, text, profile.instructions_for(language))
        comfort_session_id = f"{session_id}-report-comfort-{uuid4().hex[:8]}"
        done = asyncio.Event()
        errors: list[str] = []
        result: dict[str, Any] = {}

        async def on_event(stage: str, _event: dict[str, Any], metadata: dict[str, Any] | None) -> None:
            if stage == "assistant_audio_end" and metadata:
                result.update(metadata)
                done.set()

        async def on_error(message: str) -> None:
            errors.append(message)
            done.set()

        await self.omni_service.connect_session(
            session_id=comfort_session_id,
            scenario_id=scenario_id,
            language=language,
            instructions=instructions,
            profile=profile,
            on_event=on_event,
            on_error=on_error,
        )

        try:
            committed = await self.omni_service.commit_silent_user_turn(comfort_session_id)
            if not committed:
                raise RuntimeError("Omni Realtime 未能启动安抚语音生成")
            await asyncio.wait_for(done.wait(), timeout=self.timeout_seconds)
            if errors:
                raise RuntimeError(errors[-1])

            audio_url = str(result.get("audioUrl") or "")
            duration_ms = int(result.get("durationMs") or 0)
            if not audio_url or duration_ms <= 0:
                raise RuntimeError("Omni Realtime 未返回可播放的安抚语音")

            logger.info(
                "report.reassurance_audio.done session=%s comfort_session=%s duration_ms=%s",
                session_id,
                comfort_session_id,
                duration_ms,
            )
            return ReportReassuranceAudio(
                text=text,
                audio_url=audio_url,
                duration_ms=duration_ms,
                voice_profile_id=profile.profile.id,
            )
        finally:
            await self.omni_service.close_session(comfort_session_id)

    @staticmethod
    def _build_reassurance_text(language: LanguageOption, attempt_index: int) -> str:
        if language == "en":
            variants = [
                "Nice work. You have finished this round of practice. Your report is being prepared now, so please stay with me for a moment.",
                "I am organizing the key highlights, the main issues, and the next action steps for you now. The full report will be ready very soon.",
                "Thank you for waiting. I am doing the final pass on your report, and it will appear here as soon as it is ready.",
            ]
        else:
            variants = [
                "恭喜你，已经完成了这一轮训练。报告正在加速分析中，你可以先放松一下，我很快就把结果整理给你。",
                "我正在帮你梳理这次表现里的亮点、问题，还有下一步最值得练的方向。再稍等一下，完整报告马上就出来。",
                "辛苦了，我还在做最后一轮整理。等报告出来后，你会直接看到总结、能力分布和行动建议。",
            ]
        return variants[min(max(0, attempt_index), len(variants) - 1)]

    @staticmethod
    def _build_instructions(language: LanguageOption, text: str, profile_instruction: str) -> str:
        if language == "en":
            return (
                f"{profile_instruction}\n"
                "You are reassuring a user while their practice report is being generated. "
                "Speak warmly, slowly, and with natural pauses, like a real coach sitting beside the user. "
                "Do not sound rushed. "
                f"Say exactly this passage and nothing else: {text}"
            )
        return (
            f"{profile_instruction}\n"
            "你正在用户等待训练报告生成时做安抚。"
            "请用温和、真诚、偏慢的语速来表达，每个分句之间都要有自然停顿，不要像播报，不要着急。"
            "只说下面这段话，不要增减内容，不要提模型、系统、token、内部流程，也不要追加解释："
            f"{text}"
        )
