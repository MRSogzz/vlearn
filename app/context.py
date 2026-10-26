from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from app.adapters.bilibili import BilibiliAdapter
from app.adapters.youtube import YouTubeAdapter
from app.cost.budget import BudgetGuard
from app.cost.ledger import CostLedger
from app.cost.router import ModelRouter
from app.storage.cache import Cache
from app.storage.db import Database


@dataclass
class AppContext:
    config: dict
    models: dict
    db: Database
    cache: Cache
    ledger: CostLedger
    budget: BudgetGuard
    router: ModelRouter
    adapters: dict
    project_root: Path

    def adapter_for(self, platform: str):
        if platform not in self.adapters:
            raise ValueError(f"未啟用的平臺: {platform}")
        return self.adapters[platform]

    def resolve_path(self, path_str: str) -> Path:
        """相對路徑基於項目根解析，絕對路徑原樣返回。"""
        p = Path(path_str)
        return p if p.is_absolute() else (self.project_root / p).resolve()

    @classmethod
    def from_config(cls, config_path: str) -> AppContext:
        cfg_path = Path(config_path).resolve()
        if not cfg_path.exists():
            raise FileNotFoundError(f"config not found: {cfg_path}")
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))

        models_path = cfg_path.parent / "models.yaml"
        models = (yaml.safe_load(models_path.read_text(encoding="utf-8"))
                  if models_path.exists() else {"providers": {}, "routing": {}})

        # 項目根 = config/default.yaml 的上兩級（config 的父目錄）
        project_root = cfg_path.parent.parent

        def _resolve(path_str: str) -> Path:
            p = Path(path_str)
            return p if p.is_absolute() else (project_root / p).resolve()

        out_dir = _resolve(cfg["output"]["output_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        db = Database(str(out_dir / "vlearn.db"))
        cache = Cache(str(out_dir / "cache"))
        ledger = CostLedger(db)
        budget = BudgetGuard(cfg["cost"], ledger)
        router = ModelRouter(models, cfg["cost"].get("peak_hours_utc", []), ledger)

        adapters: dict = {"youtube": YouTubeAdapter(cfg["platform"].get("youtube", {}))}
        if cfg["platform"].get("bilibili", {}).get("enabled"):
            adapters["bilibili"] = BilibiliAdapter()

        return cls(config=cfg, models=models, db=db, cache=cache,
                   ledger=ledger, budget=budget, router=router, adapters=adapters,
                   project_root=project_root)
