from __future__ import annotations

from app.schemas import LanguageOption, ScenarioType, TopDimensionId


TOP_DIMENSION_ORDER: tuple[TopDimensionId, ...] = (
    "body",
    "facial_expression",
    "vocal_tone",
    "rhythm",
    "content_quality",
    "expression_structure",
)

TOP_DIMENSION_LABELS = {
    "zh": {
        "body": "肢体",
        "facial_expression": "表情",
        "vocal_tone": "语音语调",
        "rhythm": "节奏",
        "content_quality": "内容质量",
        "expression_structure": "表达结构",
    },
    "en": {
        "body": "Body",
        "facial_expression": "Facial Expression",
        "vocal_tone": "Vocal Tone",
        "rhythm": "Rhythm",
        "content_quality": "Content Quality",
        "expression_structure": "Expression Structure",
    },
}

DEFAULT_DIMENSION_WEIGHTS: dict[TopDimensionId, int] = {
    "body": 20,
    "facial_expression": 20,
    "vocal_tone": 10,
    "rhythm": 20,
    "content_quality": 10,
    "expression_structure": 20,
}

SCENARIO_WEIGHT_MAP: dict[ScenarioType, dict[TopDimensionId, int]] = {
    "host": dict(DEFAULT_DIMENSION_WEIGHTS),
    "guest-sharing": dict(DEFAULT_DIMENSION_WEIGHTS),
    "standup": dict(DEFAULT_DIMENSION_WEIGHTS),
}

COACH_TO_TOP_DIMENSIONS: dict[str, tuple[TopDimensionId, ...]] = {
    "framing": ("body",),
    "alignment": ("body",),
    "openness_or_tension": ("body", "facial_expression"),
    "gesture_naturalness": ("body",),
    "movement_or_space_use": ("body",),
    "facial_or_eye_engagement": ("facial_expression",),
    "articulation_clarity": ("vocal_tone",),
    "projection": ("vocal_tone",),
    "pace": ("rhythm",),
    "pause_placement": ("rhythm",),
    "emphasis": ("vocal_tone",),
    "intonation_or_emotional_energy": ("vocal_tone", "facial_expression"),
    "fluency": ("rhythm",),
    "concision": ("content_quality",),
    "filler_or_redundancy": ("content_quality", "rhythm"),
    "repetition_or_circularity": ("expression_structure",),
    "structure": ("expression_structure",),
    "point_clarity": ("expression_structure", "content_quality"),
    "support": ("content_quality",),
    "progression": ("expression_structure",),
}

SUB_DIMENSION_LABELS = {
    "zh": {
        "framing": "入镜与构图",
        "alignment": "体态与对齐",
        "openness_or_tension": "松弛度与紧绷感",
        "gesture_naturalness": "手势自然度",
        "movement_or_space_use": "走位与空间使用",
        "facial_or_eye_engagement": "表情与眼神互动",
        "articulation_clarity": "吐字与清晰度",
        "projection": "音量与投射感",
        "pace": "语速",
        "pause_placement": "断句与停顿",
        "emphasis": "重音与强调",
        "intonation_or_emotional_energy": "起伏与情绪状态",
        "fluency": "卡壳与流畅度",
        "concision": "简洁度",
        "filler_or_redundancy": "口头禅与冗余",
        "repetition_or_circularity": "重复与绕圈",
        "structure": "逻辑结构",
        "point_clarity": "观点清晰度",
        "support": "例子与支撑",
        "progression": "收束与推进",
        "transcript_structure": "结构推进",
        "transcript_concision": "表达简洁度",
        "transcript_fluency": "文本流畅度",
        "transcript_audience": "听众感",
    },
    "en": {
        "framing": "Framing",
        "alignment": "Alignment",
        "openness_or_tension": "Openness vs Tension",
        "gesture_naturalness": "Gesture Naturalness",
        "movement_or_space_use": "Movement & Space Use",
        "facial_or_eye_engagement": "Facial & Eye Engagement",
        "articulation_clarity": "Articulation Clarity",
        "projection": "Projection",
        "pace": "Pace",
        "pause_placement": "Pause Placement",
        "emphasis": "Emphasis",
        "intonation_or_emotional_energy": "Intonation & Energy",
        "fluency": "Fluency",
        "concision": "Concision",
        "filler_or_redundancy": "Filler & Redundancy",
        "repetition_or_circularity": "Repetition & Circularity",
        "structure": "Structure",
        "point_clarity": "Point Clarity",
        "support": "Support",
        "progression": "Progression",
        "transcript_structure": "Structural Progression",
        "transcript_concision": "Concision",
        "transcript_fluency": "Transcript Fluency",
        "transcript_audience": "Audience Awareness",
    },
}


def top_dimension_label(dimension_id: TopDimensionId, language: LanguageOption) -> str:
    return TOP_DIMENSION_LABELS["en" if language == "en" else "zh"][dimension_id]


def sub_dimension_label(sub_dimension_id: str, language: LanguageOption) -> str:
    labels = SUB_DIMENSION_LABELS["en" if language == "en" else "zh"]
    return labels.get(sub_dimension_id, sub_dimension_id.replace("_", " ").title())


def scenario_weights(scenario_id: ScenarioType) -> dict[TopDimensionId, int]:
    return SCENARIO_WEIGHT_MAP[scenario_id]
