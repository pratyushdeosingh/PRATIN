"""Live execution trace for the Capital Agent run.

The Capital Agents page shows a step-by-step trace while the agent works.
Each step here maps to a REAL backend action (research call, cache hit,
scoring, pricing, decision) — never a fake animation. Steps are recorded
as they happen so the UI can render progress and the final trace stays
visible for the judge to inspect.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Step states: pending -> running -> done / failed / skipped
PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
SKIPPED = "skipped"

_STEPS: list[str] = [
    "observe_invoice",
    "load_risk",
    "research_companies",
    "search_market",
    "select_providers",
    "research_providers",
    "extract_terms",
    "score_providers",
    "evaluate_suitability",
    "check_constraints",
    "price_financing",
    "generate_offer",
]

_LABELS: dict[str, str] = {
    "observe_invoice": "Invoice received",
    "load_risk": "Risk assessment loaded",
    "research_companies": "Researching seller & client companies",
    "search_market": "Searching capital market",
    "select_providers": "Selecting relevant providers",
    "research_providers": "Researching official provider sources",
    "extract_terms": "Extracting financing terms",
    "score_providers": "Calculating provider scores",
    "evaluate_suitability": "Evaluating provider suitability",
    "check_constraints": "Checking capital constraints",
    "price_financing": "Calculating financing terms",
    "generate_offer": "Generating final offer",
}


@dataclass
class TraceStep:
    key: str
    label: str
    state: str = PENDING
    detail: str = ""
    at: str = ""

    def to_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "state": self.state,
                "detail": self.detail, "at": self.at}


class ExecutionTrace:
    """Thread-safe step recorder."""

    def __init__(self):
        self._lock = threading.Lock()
        self.steps: list[TraceStep] = [TraceStep(key=k, label=_LABELS[k]) for k in _STEPS]
        self.started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.finished_at: str | None = None
        self.error: str | None = None

    def mark(self, key: str, state: str, detail: str = "") -> None:
        with self._lock:
            for step in self.steps:
                if step.key == key:
                    step.state = state
                    step.detail = detail
                    step.at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    break

    def start(self, key: str) -> None:
        self.mark(key, RUNNING)

    def done(self, key: str, detail: str = "") -> None:
        self.mark(key, DONE, detail)

    def skip(self, key: str, detail: str = "") -> None:
        self.mark(key, SKIPPED, detail)

    def fail(self, key: str, detail: str = "") -> None:
        self.mark(key, FAILED, detail)

    def finish(self) -> None:
        self.finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "error": self.error,
                "steps": [s.to_dict() for s in self.steps],
            }
