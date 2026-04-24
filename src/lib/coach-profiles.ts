import rawProfiles from "../../ai_coach/profiles.json";

export interface CoachVoiceProfile {
  tone: string;
  paceDetail: string;
  memoryPoint: string;
}

export interface CoachQAStyle {
  providerVoiceId: string;
  omniVoiceId: string;
  displayVoiceLabel: string;
  fillersZh: string[];
  instructionsZh: string;
  instructionsEn: string;
}

export interface CoachReportStyle {
  instructionZh: string;
}

export interface CoachProfile {
  id: string;
  name: string;
  personaType: string;
  originName: string;
  avatarFile: string;
  avatarSrc: string;
  slogan: string;
  bio: string;
  liveStatus: string;
  voiceProfile: CoachVoiceProfile;
  qaStyle: CoachQAStyle;
  reportStyle: CoachReportStyle;
}

type RawCoachProfile = {
  id: string;
  name: string;
  persona_type: string;
  origin_name: string;
  avatar_file: string;
  slogan: string;
  bio: string;
  live_status: string;
  voice_profile: {
    tone: string;
    pace_detail: string;
    memory_point: string;
  };
  qa_style: {
    provider_voice_id: string;
    omni_voice_id: string;
    display_voice_label: string;
    fillers_zh: string[];
    instructions_zh: string;
    instructions_en: string;
  };
  report_style: {
    instruction_zh: string;
  };
};

const coachProfiles = (rawProfiles as RawCoachProfile[]).map<CoachProfile>((profile) => ({
  id: profile.id,
  name: profile.name,
  personaType: profile.persona_type,
  originName: profile.origin_name,
  avatarFile: profile.avatar_file,
  avatarSrc: `/ai-coach/${profile.avatar_file}`,
  slogan: profile.slogan,
  bio: profile.bio,
  liveStatus: profile.live_status,
  voiceProfile: {
    tone: profile.voice_profile.tone,
    paceDetail: profile.voice_profile.pace_detail,
    memoryPoint: profile.voice_profile.memory_point,
  },
  qaStyle: {
    providerVoiceId: profile.qa_style.provider_voice_id,
    omniVoiceId: profile.qa_style.omni_voice_id,
    displayVoiceLabel: profile.qa_style.display_voice_label,
    fillersZh: profile.qa_style.fillers_zh,
    instructionsZh: profile.qa_style.instructions_zh,
    instructionsEn: profile.qa_style.instructions_en,
  },
  reportStyle: {
    instructionZh: profile.report_style.instruction_zh,
  },
}));

const coachProfileMap = new Map(coachProfiles.map((profile) => [profile.id, profile]));

export function getCoachProfiles() {
  return coachProfiles;
}

export function getDefaultCoachProfile() {
  return coachProfiles[0] ?? null;
}

export function getDefaultCoachProfileId() {
  return getDefaultCoachProfile()?.id ?? "";
}

export function getCoachProfileById(coachProfileId: string | null | undefined) {
  if (!coachProfileId) {
    return null;
  }
  return coachProfileMap.get(coachProfileId) ?? null;
}

export function isCoachProfileId(value: string | null | undefined) {
  return !!value && coachProfileMap.has(value);
}
