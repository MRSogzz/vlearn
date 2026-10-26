"""預算守衛：超 per_video 降級，超 daily 停止或降級。"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.cost.ledger import CostLedger


@dataclass
class RuntimeProfile:
    """運行期可變的降級開關。"""
    vision_policy: str = "on_demand"          # always | on_demand | none
    max_backtracks: int = 5
    batch_windows: bool = True
    degraded: list[str] = field(default_factory=list)

    def apply(self, path: str, value):
        if path == "vision.policy":
            self.vision_policy = value
        elif path == "evidence.max_backtracks":
            self.max_backtracks = value
        elif path == "summary.batch_windows":
            self.batch_windows = value
        self.degraded.append(f"{path}={value}")


class BudgetGuard:
    def __init__(self, cfg: dict, ledger: CostLedger):
        self.cfg = cfg
        self.ledger = ledger

    def profile(self) -> RuntimeProfile:
        return RuntimeProfile(
            vision_policy=self.cfg.get("vision", {}).get("policy", "on_demand")
            if False else "on_demand",  # 由調用方覆蓋
            max_backtracks=5,
        )

    def should_degrade(self, run_id: str) -> bool:
        spent = self.ledger.run_spend(run_id)
        return spent > float(self.cfg["per_video_usd"])

    def daily_exceeded(self) -> bool:
        s = self.ledger.summary(daily=True)
        return s["total_usd"] > float(self.cfg["daily_usd"])

    def on_exceed(self) -> str:
        return self.cfg.get("on_exceed", "degrade")

    def degrade_order(self) -> list[dict]:
        return list(self.cfg.get("degrade_order", []))
