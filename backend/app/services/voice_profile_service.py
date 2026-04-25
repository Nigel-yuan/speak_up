import json
from dataclasses import dataclass
from pathlib import Path

from app.schemas import LanguageOption, VoiceProfile


@dataclass(frozen=True)
class VoiceProfileConfig:
    profile: VoiceProfile
    coach_name: str
    persona_type: str
    provider_voice_id: str
    omni_voice_id: str
    instructions_zh: str
    instructions_en: str
    report_instruction_zh: str
    report_style_examples: list[dict[str, str]]

    def instructions_for(self, language: LanguageOption) -> str:
        return self.instructions_en if language == "en" else self.instructions_zh


class VoiceProfileService:
    def __init__(self) -> None:
        self._profiles = self._load_profiles()

    def _load_profiles(self) -> dict[str, VoiceProfileConfig]:
        profile_path = Path(__file__).resolve().parents[3] / "ai_coach" / "profiles.json"
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
        gender_map = {
            "duojiong_he": "male",
            "youge_hu": "male",
            "xiaoling_jia": "female",
            "daxing_jin": "female",
        }
        style_map = {
            "温暖型": "gentle",
            "严肃型": "professional",
            "鼓励型": "encouraging",
            "压力型": "firm",
        }

        profiles: dict[str, VoiceProfileConfig] = {}
        for item in payload:
            coach_id = str(item["id"])
            qa_style = item["qa_style"]
            report_style = item["report_style"]
            persona_type = str(item["persona_type"])
            profiles[coach_id] = VoiceProfileConfig(
                profile=VoiceProfile(
                    id=coach_id,
                    label=str(qa_style["display_voice_label"]),
                    gender=gender_map.get(coach_id, "male"),
                    style=style_map.get(persona_type, "professional"),
                ),
                coach_name=str(item["name"]),
                persona_type=persona_type,
                provider_voice_id=str(qa_style["provider_voice_id"]),
                omni_voice_id=str(qa_style["omni_voice_id"]),
                instructions_zh=str(qa_style["instructions_zh"]),
                instructions_en=str(qa_style["instructions_en"]),
                report_instruction_zh=str(report_style["instruction_zh"]),
                report_style_examples=self._normalize_report_style_examples(
                    report_style.get("dimension_examples", [])
                ),
            )
        return profiles

    @staticmethod
    def _normalize_report_style_examples(value: object) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        examples: list[dict[str, str]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            dimension = str(item.get("dimension") or "").strip()
            positive = str(item.get("positive") or "").strip()
            negative = str(item.get("negative") or "").strip()
            if not dimension or not positive or not negative:
                continue
            examples.append(
                {
                    "dimension": dimension,
                    "positive": positive,
                    "negative": negative,
                }
            )
        return examples

    def list_profiles(self) -> list[VoiceProfile]:
        return [config.profile for config in self._profiles.values()]

    def get(self, profile_id: str | None) -> VoiceProfileConfig:
        if profile_id and profile_id in self._profiles:
            return self._profiles[profile_id]
        return next(iter(self._profiles.values()))
