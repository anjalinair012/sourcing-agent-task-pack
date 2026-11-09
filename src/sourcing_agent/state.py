"""Run state, saved to disk after every step so a killed run can carry on."""

from __future__ import annotations

import json
import os
from pathlib import Path


class State:
    """One JSON file. Per vacancy: iteration, soft filters, profiles seen, scores, trace."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = {"vacancies": {}}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))

    def exists(self) -> bool:
        return self.path.exists()

    def vacancy(self, vid: str) -> dict:
        return self.data["vacancies"].setdefault(vid, {
            "iteration": 0,       # iterations finished
            "soft": {},           # soft filters for the next round
            "seen": {},           # profile_id -> profile (every profile we paid for)
            "scores": {},         # profile_id -> {"score", "passed", "hits", "evidence"}
            "trace": [],          # one dict per finished iteration
            "stop_reason": None,
        })

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data), encoding="utf-8")
        os.replace(tmp, self.path)  # atomic: a kill never leaves half a file
