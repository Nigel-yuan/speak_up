import type { LanguageOption, ScenarioOption, ScenarioType } from "@/types/session";

const languageOptions = [
  { label: "中文", value: "zh" },
  { label: "English", value: "en" },
] as const;

interface SessionToolbarProps {
  language: LanguageOption;
  onHistoryToggle: () => void;
  onLanguageChange: (language: LanguageOption) => void;
  onScenarioChange: (scenario: ScenarioType) => void;
  onScenarioToggle: () => void;
  scenario: ScenarioType;
  scenarioOpen: boolean;
  scenarios: ScenarioOption[];
}

export function SessionToolbar({
  language,
  onHistoryToggle,
  onLanguageChange,
  onScenarioChange,
  onScenarioToggle,
  scenario,
  scenarioOpen,
  scenarios,
}: SessionToolbarProps) {
  const currentScenario = scenarios.find((item) => item.id === scenario) ?? null;

  return (
    <div className="relative flex items-center gap-3">
      <button
        type="button"
        onClick={onScenarioToggle}
        className="rounded-full bg-violet-600 px-4 py-2 text-sm font-semibold text-white shadow-[0_10px_25px_rgba(109,40,217,0.28)] transition hover:bg-violet-500"
      >
        切换场景 · {currentScenario?.title ?? "加载中"}
      </button>
      <button
        type="button"
        onClick={onHistoryToggle}
        className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 shadow-[0_10px_25px_rgba(15,23,42,0.06)] transition hover:border-violet-200 hover:bg-violet-50 hover:text-violet-700"
      >
        历史演讲
      </button>

      {scenarioOpen ? (
        <div className="absolute left-0 top-full z-20 mt-3 w-[360px] rounded-[24px] border border-white/70 bg-white/95 p-3 shadow-[0_18px_45px_rgba(15,23,42,0.12)] backdrop-blur">
          <p className="px-3 pb-2 pt-1 text-xs font-semibold uppercase tracking-[0.22em] text-slate-400">选择场景</p>
          <div className="space-y-2">
            {scenarios.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  onScenarioChange(item.id);
                  onScenarioToggle();
                }}
                className={`w-full rounded-2xl px-4 py-3 text-left transition ${
                  scenario === item.id
                    ? "bg-slate-950 text-white"
                    : "bg-slate-50 text-slate-700 hover:bg-slate-100"
                }`}
              >
                <p className="text-sm font-semibold">{item.title}</p>
                <p className={`mt-1 text-xs leading-5 ${scenario === item.id ? "text-slate-300" : "text-slate-500"}`}>
                  {item.subtitle}
                </p>
              </button>
            ))}
          </div>

          <div className="mt-3 border-t border-slate-200 px-3 pt-3">
            <p className="mb-2 text-xs font-semibold uppercase tracking-[0.22em] text-slate-400">语言</p>
            <div className="flex gap-2">
              {languageOptions.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => onLanguageChange(item.value)}
                  className={`rounded-full px-4 py-2 text-sm font-semibold transition ${
                    language === item.value
                      ? "bg-violet-600 text-white"
                      : "bg-violet-50 text-violet-700 hover:bg-violet-100"
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
