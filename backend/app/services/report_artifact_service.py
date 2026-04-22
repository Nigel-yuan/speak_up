from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from pathlib import Path

from app.schemas import LanguageOption, ReportArtifactEntry, ReportArtifactType, ScenarioType


class ReportArtifactService:
    def __init__(self, output_root: str | None = None) -> None:
        self.output_root = Path(output_root or "output/report_data")
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def _session_dir(self, session_id: str) -> Path:
        return self.output_root / session_id

    def _core_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "session_core.json"

    def _artifacts_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "session_artifacts.jsonl"

    async def init_session(
        self,
        *,
        session_id: str,
        scenario_id: ScenarioType,
        language: LanguageOption,
    ) -> None:
        async with self._locks[session_id]:
            session_dir = self._session_dir(session_id)
            session_dir.mkdir(parents=True, exist_ok=True)
            self._core_path(session_id).write_text(
                json.dumps(
                    {
                        "sessionId": session_id,
                        "scenarioId": scenario_id,
                        "language": language,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    async def append_artifact(
        self,
        *,
        session_id: str,
        artifact_type: ReportArtifactType,
        timestamp_ms: int,
        payload: dict,
    ) -> None:
        entry = ReportArtifactEntry(
            sessionId=session_id,
            type=artifact_type,
            timestampMs=max(0, timestamp_ms),
            payload=payload,
        )
        async with self._locks[session_id]:
            session_dir = self._session_dir(session_id)
            session_dir.mkdir(parents=True, exist_ok=True)
            with self._artifacts_path(session_id).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry.model_dump(), ensure_ascii=False))
                handle.write("\n")

    async def read_artifacts(self, session_id: str) -> list[ReportArtifactEntry]:
        path = self._artifacts_path(session_id)
        if not path.exists():
            return []
        async with self._locks[session_id]:
            entries: list[ReportArtifactEntry] = []
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                entries.append(ReportArtifactEntry.model_validate_json(stripped))
            return entries
