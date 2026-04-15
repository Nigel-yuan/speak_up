import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type {
  CoachDimensionId,
  CoachDimensionState,
  CoachDisplayStatus,
  CoachPanelState,
  LanguageOption,
} from "@/types/session";

function buildFallbackCoachPanel(language: LanguageOption): CoachPanelState {
  const isEnglish = language === "en";
  const summaryTitle = isEnglish ? "Keep speaking while AI updates your coaching" : "继续演讲，AI 正在同步更新反馈";
  const summaryDetail = isEnglish
    ? "The panel below will keep updating as your delivery changes."
    : "下方三项会随着你的声音、画面和内容持续更新。";
  const analyzingHeadlineMap: Record<CoachDimensionId, string> = {
    body_expression: isEnglish ? "Updating body delivery" : "正在更新肢体反馈",
    voice_pacing: isEnglish ? "Updating vocal pacing" : "正在更新语音反馈",
    content_expression: isEnglish ? "Updating content clarity" : "正在更新内容反馈",
  };
  const analyzingDetailMap: Record<CoachDimensionId, string> = {
    body_expression: isEnglish ? "Keep your current rhythm" : "保持当前节奏",
    voice_pacing: isEnglish ? "Keep your current rhythm" : "保持当前节奏",
    content_expression: isEnglish ? "Keep going and this card will update shortly" : "继续往下讲",
  };

  const buildDimension = (id: CoachDimensionId): CoachDimensionState => ({
    id,
    status: "analyzing",
    headline: analyzingHeadlineMap[id],
    detail: analyzingDetailMap[id],
    updatedAtMs: 0,
    source: "system",
  });

  return {
    summary: {
      title: summaryTitle,
      detail: summaryDetail,
      sourceDimension: null,
      updatedAtMs: 0,
    },
    bodyExpression: buildDimension("body_expression"),
    voicePacing: buildDimension("voice_pacing"),
    contentExpression: buildDimension("content_expression"),
  };
}

function getDimensionTitle(id: CoachDimensionId, language: LanguageOption) {
  if (language === "en") {
    switch (id) {
      case "body_expression":
        return "Body";
      case "voice_pacing":
        return "Voice";
      default:
        return "Content";
    }
  }

  switch (id) {
    case "body_expression":
      return "肢体 & 表情";
    case "voice_pacing":
      return "语音语调 & 节奏";
    default:
      return "内容 & 表达";
  }
}

function getStatusLabel(status: CoachDisplayStatus, language: LanguageOption) {
  if (language === "en") {
    switch (status) {
      case "doing_well":
        return "Strong";
      case "stable":
        return "Okay";
      case "adjust_now":
        return "Fix";
      default:
        return "Syncing";
    }
  }

  switch (status) {
    case "doing_well":
      return "很好";
    case "stable":
      return "还行";
    case "adjust_now":
      return "调整";
    default:
      return "分析中";
  }
}

function getStatusTone(status: CoachDisplayStatus) {
  switch (status) {
    case "doing_well":
      return "positive" as const;
    case "adjust_now":
      return "warning" as const;
    default:
      return "neutral" as const;
  }
}

function getEnergyLevel(status: CoachDisplayStatus) {
  switch (status) {
    case "doing_well":
      return 100;
    case "stable":
      return 62;
    case "adjust_now":
      return 24;
    default:
      return 38;
  }
}

function getEnergyColor(status: CoachDisplayStatus) {
  switch (status) {
    case "doing_well":
      return "from-emerald-400 to-emerald-500";
    case "stable":
      return "from-sky-400 to-sky-500";
    case "adjust_now":
      return "from-amber-400 to-amber-500";
    default:
      return "from-slate-400 to-slate-500";
  }
}

function getShortCue(dimension: CoachDimensionState, language: LanguageOption) {
  const zhMap: Record<CoachDimensionId, Record<CoachDisplayStatus, string>> = {
    body_expression: {
      doing_well: "继续保持",
      stable: "再放松些",
      adjust_now: "先调体态",
      analyzing: "继续演讲",
    },
    voice_pacing: {
      doing_well: "节奏不错",
      stable: "稳住节奏",
      adjust_now: "放慢半拍",
      analyzing: "继续表达",
    },
    content_expression: {
      doing_well: "主线清楚",
      stable: "再收短些",
      adjust_now: "先讲结论",
      analyzing: "继续展开",
    },
  };
  const enMap: Record<CoachDimensionId, Record<CoachDisplayStatus, string>> = {
    body_expression: {
      doing_well: "Keep it",
      stable: "Stay open",
      adjust_now: "Reset pose",
      analyzing: "Keep going",
    },
    voice_pacing: {
      doing_well: "Nice flow",
      stable: "Hold pace",
      adjust_now: "Slow down",
      analyzing: "Keep going",
    },
    content_expression: {
      doing_well: "Clear line",
      stable: "Trim it",
      adjust_now: "Lead first",
      analyzing: "Build it",
    },
  };

  return language === "en"
    ? enMap[dimension.id][dimension.status]
    : zhMap[dimension.id][dimension.status];
}

function truncateForDisplay(
  text: string,
  language: LanguageOption,
  zhMax: number,
  enMax: number,
  withEllipsis = true,
) {
  const maxLength = language === "en" ? enMax : zhMax;
  const normalized = text.trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  if (!withEllipsis) {
    return normalized.slice(0, maxLength).trimEnd();
  }
  return `${normalized.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`;
}

function EnergyBar({ status }: { status: CoachDisplayStatus }) {
  const level = getEnergyLevel(status);
  const fillColor = getEnergyColor(status);

  return (
    <div className="h-3.5 flex-none overflow-hidden rounded-full bg-slate-200 shadow-[inset_0_1px_2px_rgba(15,23,42,0.12)]">
      <div
        className={`h-full rounded-full bg-gradient-to-r transition-[width] duration-300 ${fillColor}`}
        style={{ width: `${level}%` }}
      />
    </div>
  );
}

function DimensionCard({
  dimension,
  language,
  focused,
}: {
  dimension: CoachDimensionState;
  language: LanguageOption;
  focused: boolean;
}) {
  const headline = truncateForDisplay(dimension.headline, language, 18, 36);
  const cue = truncateForDisplay(getShortCue(dimension, language), language, 6, 12);

  return (
    <div
      className={`flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border px-4 py-2 shadow-[0_10px_24px_rgba(15,23,42,0.05)] ${
        focused ? "border-slate-900/15 bg-slate-50" : "border-slate-200 bg-white"
      }`}
    >
      <div className="mb-1.5 flex items-center justify-between gap-3">
        <p className="text-sm font-semibold text-slate-900">{getDimensionTitle(dimension.id, language)}</p>
        <Badge tone={getStatusTone(dimension.status)}>{getStatusLabel(dimension.status, language)}</Badge>
      </div>

      <EnergyBar status={dimension.status} />

      <div className="mt-1.5 flex min-h-0 items-center justify-between gap-3">
        <p
          className="min-w-0 text-sm font-medium leading-5 text-slate-600"
          style={{
            display: "-webkit-box",
            WebkitBoxOrient: "vertical",
            WebkitLineClamp: 1,
            overflow: "hidden",
          }}
        >
          {headline}
        </p>
        <span className="shrink-0 rounded-full bg-slate-900 px-2.5 py-1 text-[11px] font-semibold text-white">
          {cue}
        </span>
      </div>
    </div>
  );
}

export function LiveAnalysisPanel({
  coachPanel,
  language,
}: {
  coachPanel: CoachPanelState | null;
  language: LanguageOption;
}) {
  const activePanel = coachPanel ?? buildFallbackCoachPanel(language);
  const summaryTitle = truncateForDisplay(activePanel.summary.title, language, 22, 42);
  const summaryDetail = truncateForDisplay(activePanel.summary.detail, language, 22, 44, false);
  const dimensions = [
    activePanel.bodyExpression,
    activePanel.voicePacing,
    activePanel.contentExpression,
  ];

  return (
    <Card className="flex h-full min-h-0 flex-col overflow-hidden rounded-[28px] border-white/60 bg-white/85 p-5 shadow-[0_18px_45px_rgba(15,23,42,0.08)] backdrop-blur">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <p className="text-sm text-slate-500">{language === "en" ? "Synchronized analysis" : "同步分析"}</p>
          <h3 className="text-lg font-semibold text-slate-950">AI Live Coach</h3>
        </div>
        <Badge
          tone={getStatusTone(
            activePanel.bodyExpression.status === "adjust_now" ||
              activePanel.voicePacing.status === "adjust_now" ||
              activePanel.contentExpression.status === "adjust_now"
              ? "adjust_now"
              : "stable",
          )}
        >
          {language === "en" ? "Live" : "实时反馈"}
        </Badge>
      </div>

      <div className="h-[96px] flex-none overflow-hidden rounded-[26px] bg-slate-950 px-5 py-3 text-white shadow-[0_18px_40px_rgba(15,23,42,0.22)]">
        <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-400">
          {language === "en" ? "Current focus" : "当前重点"}
        </p>
        <p
          className="mt-1.5 text-[15px] font-semibold leading-6 text-white"
          style={{
            display: "-webkit-box",
            WebkitBoxOrient: "vertical",
            WebkitLineClamp: 1,
            overflow: "hidden",
          }}
        >
          {summaryTitle}
        </p>
        <p
          className="mt-1 text-[12px] leading-5 text-slate-300"
          style={{
            display: "-webkit-box",
            WebkitBoxOrient: "vertical",
            WebkitLineClamp: 1,
            overflow: "hidden",
          }}
        >
          {summaryDetail}
        </p>
      </div>

      <div className="mt-3 min-h-0 flex-1 overflow-hidden">
        <div className="grid h-full min-h-0 grid-rows-[repeat(3,minmax(0,1fr))] gap-2.5">
        {dimensions.map((dimension) => (
          <DimensionCard
            key={dimension.id}
            dimension={dimension}
            language={language}
            focused={activePanel.summary.sourceDimension === dimension.id}
          />
        ))}
        </div>
      </div>
    </Card>
  );
}
