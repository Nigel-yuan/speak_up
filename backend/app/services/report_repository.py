from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from pathlib import Path

from pydantic import ValidationError

from app.schemas import (
    LanguageOption,
    ReportRepositoryState,
    ReportWindowPack,
    ScenarioType,
    SessionReport,
)


class ReportRepository:
    def __init__(self, output_root: str | None = None) -> None:
        self.output_root = Path(output_root or "output/report_data")
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def _session_dir(self, session_id: str) -> Path:
        return self.output_root / session_id

    def _state_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "report_state.json"

    def _windows_dir(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "windows"

    def _final_report_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "final_report.json"

    async def init_session(
        self,
        *,
        session_id: str,
        scenario_id: ScenarioType,
        language: LanguageOption,
        coach_profile_id: str | None = None,
    ) -> None:
        async with self._locks[session_id]:
            session_dir = self._session_dir(session_id)
            session_dir.mkdir(parents=True, exist_ok=True)
            self._windows_dir(session_id).mkdir(parents=True, exist_ok=True)
            if not self._state_path(session_id).exists():
                state = ReportRepositoryState(
                    sessionId=session_id,
                    scenarioId=scenario_id,
                    language=language,
                    coachProfileId=coach_profile_id,
                )
                self._write_json(self._state_path(session_id), state.model_dump())

    async def get_state(self, session_id: str) -> ReportRepositoryState | None:
        path = self._state_path(session_id)
        if not path.exists():
            return None
        async with self._locks[session_id]:
            return ReportRepositoryState.model_validate_json(path.read_text(encoding="utf-8"))

    async def save_state(self, state: ReportRepositoryState) -> None:
        async with self._locks[state.sessionId]:
            self._session_dir(state.sessionId).mkdir(parents=True, exist_ok=True)
            self._write_json(self._state_path(state.sessionId), state.model_dump())

    async def update_state(self, session_id: str, **changes) -> ReportRepositoryState:
        state = await self.get_state(session_id)
        if state is None:
            raise FileNotFoundError(f"report state missing for session {session_id}")
        next_state = state.model_copy(update=changes)
        await self.save_state(next_state)
        return next_state

    async def list_window_packs(self, session_id: str) -> list[ReportWindowPack]:
        windows_dir = self._windows_dir(session_id)
        if not windows_dir.exists():
            return []
        async with self._locks[session_id]:
            packs: list[ReportWindowPack] = []
            for path in sorted(windows_dir.glob("*.json")):
                try:
                    packs.append(ReportWindowPack.model_validate_json(path.read_text(encoding="utf-8")))
                except ValidationError:
                    continue
            return packs

    async def save_window_pack(self, session_id: str, pack: ReportWindowPack) -> None:
        async with self._locks[session_id]:
            windows_dir = self._windows_dir(session_id)
            windows_dir.mkdir(parents=True, exist_ok=True)
            self._write_json(windows_dir / f"{pack.windowId}.json", pack.model_dump())

    async def get_final_report(self, session_id: str) -> SessionReport | None:
        path = self._final_report_path(session_id)
        if not path.exists():
            return None
        async with self._locks[session_id]:
            try:
                return SessionReport.model_validate_json(path.read_text(encoding="utf-8"))
            except ValidationError:
                return None

    async def save_final_report(self, session_id: str, report: SessionReport) -> None:
        async with self._locks[session_id]:
            self._session_dir(session_id).mkdir(parents=True, exist_ok=True)
            self._write_json(self._final_report_path(session_id), report.model_dump())

    async def mark_failed(self, session_id: str, message: str) -> None:
        state = await self.get_state(session_id)
        if state is None:
            return
        await self.save_state(
            state.model_copy(
                update={
                    "status": "failed",
                    "errorMessage": message[:500],
                }
            )
        )

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
