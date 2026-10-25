from __future__ import annotations
from datetime import datetime, timezone

from app.storage.db import Database


class CostLedger:
    def __init__(self, db: Database):
        self.db = db

    def record(self, run_id: str, provider: str, model: str, *,
               input_tokens: int = 0, output_tokens: int = 0, image_tokens: int = 0,
               usd: float = 0.0, is_peak: bool = False, stage: str = "") -> None:
        self.db.add_cost({
            "run_id": run_id, "provider": provider, "model": model,
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "image_tokens": image_tokens, "usd": usd, "is_peak": is_peak, "stage": stage,
        })

    def summary(self, daily: bool = True) -> dict:
        return self.db.cost_summary(daily=daily)

    def run_spend(self, run_id: str) -> float:
        return self.db.cost_for_run(run_id)