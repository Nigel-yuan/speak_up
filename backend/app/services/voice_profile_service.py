from dataclasses import dataclass

from app.schemas import LanguageOption, VoiceProfile


@dataclass(frozen=True)
class VoiceProfileConfig:
    profile: VoiceProfile
    provider_voice_id: str
    omni_voice_id: str
    instructions_zh: str
    instructions_en: str

    def instructions_for(self, language: LanguageOption) -> str:
        return self.instructions_en if language == "en" else self.instructions_zh


class VoiceProfileService:
    def __init__(self) -> None:
        self._profiles: dict[str, VoiceProfileConfig] = {
            "female_professional_01": VoiceProfileConfig(
                profile=VoiceProfile(
                    id="female_professional_01",
                    label="女声 · 专业",
                    gender="female",
                    style="professional",
                ),
                provider_voice_id="Cherry",
                omni_voice_id="Tina",
                instructions_zh="你是专业、冷静、清晰的 AI 面试官。语速适中，停顿干净，语气克制，像成熟的评审老师。",
                instructions_en="You are a calm, professional AI interviewer. Speak clearly with measured pacing and restrained confidence.",
            ),
            "male_professional_01": VoiceProfileConfig(
                profile=VoiceProfile(
                    id="male_professional_01",
                    label="男声 · 专业",
                    gender="male",
                    style="professional",
                ),
                provider_voice_id="Ethan",
                omni_voice_id="Raymond",
                instructions_zh="你是专业、稳重、直接的 AI 面试官。语速中等，吐字清楚，句尾干净，像成熟的商务评审。",
                instructions_en="You are a steady, direct AI interviewer. Speak with medium pace, clear diction, and a polished business tone.",
            ),
            "female_gentle_01": VoiceProfileConfig(
                profile=VoiceProfile(
                    id="female_gentle_01",
                    label="女声 · 温和",
                    gender="female",
                    style="gentle",
                ),
                provider_voice_id="Serena",
                omni_voice_id="Liora Mira",
                instructions_zh="你是温和、友好、鼓励式的 AI 教练。语速自然，语气亲切，但表达依然清楚专业。",
                instructions_en="You are a warm and encouraging AI coach. Speak naturally, kindly, and still sound clear and professional.",
            ),
            "male_firm_01": VoiceProfileConfig(
                profile=VoiceProfile(
                    id="male_firm_01",
                    label="男声 · 直接",
                    gender="male",
                    style="firm",
                ),
                provider_voice_id="Ethan",
                omni_voice_id="Raymond",
                instructions_zh="你是直接、利落、有边界感的 AI 评委。语速适中偏快，重点句更干脆，不拖沓。",
                instructions_en="You are a firm, concise AI judge. Speak at a slightly brisk pace and land key lines crisply.",
            ),
        }

    def list_profiles(self) -> list[VoiceProfile]:
        return [config.profile for config in self._profiles.values()]

    def get(self, profile_id: str | None) -> VoiceProfileConfig:
        if profile_id and profile_id in self._profiles:
            return self._profiles[profile_id]
        return self._profiles["female_professional_01"]
