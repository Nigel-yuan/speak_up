import { isCoachProfileId } from "@/lib/coach-profiles";
import type { ScenarioType } from "@/types/session";

import { ReportClient, type ReportRouteState } from "./report-client";

const VALID_SCENARIOS = new Set<ScenarioType>(["general", "host", "guest-sharing", "standup"]);

type ReportSearchParams = Promise<Record<string, string | string[] | undefined>>;

function firstParam(value: string | string[] | undefined): string | null {
  if (Array.isArray(value)) {
    return value[0] ?? null;
  }
  return value ?? null;
}

function parseScenario(value: string | null): ScenarioType | null {
  return value && VALID_SCENARIOS.has(value as ScenarioType) ? (value as ScenarioType) : null;
}

export default async function ReportPage({
  searchParams,
}: {
  searchParams: ReportSearchParams;
}) {
  const params = await searchParams;
  const coachProfileId = firstParam(params.coach);
  const routeState: ReportRouteState = {
    sessionId: firstParam(params.sessionId),
    scenarioId: parseScenario(firstParam(params.scenario)),
    coachProfileId: isCoachProfileId(coachProfileId) ? coachProfileId : null,
  };

  return <ReportClient initialRouteState={routeState} />;
}
