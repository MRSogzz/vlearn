"""後臺 job：SQLite + 線程池。立即返回 job_id，客戶端輪詢。"""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

from app.context import AppContext


class JobRunner:
    def __init__(self, ctx: AppContext, max_workers: int = 2):
        self.ctx = ctx
        self.pool = ThreadPoolExecutor(max_workers=max_workers,
                                       thread_name_prefix="vlearn-job")

    def submit_analyze(self, video_id: str, profile: str = "standard") -> str:
        from app.orchestrator import Orchestrator
        job_id = f"job_{uuid.uuid4().hex[:10]}"
        self.ctx.db.create_job(job_id, video_id)

        def _run():
            try:
                self.ctx.db.update_job(job_id, status="running", stage="start")
                r = Orchestrator(self.ctx).analyze(
                    video_id, profile,
                    _progress=lambda s, p: self.ctx.db.update_job(
                        job_id, stage=s, progress=p))
                self.ctx.db.update_job(job_id, status="done", stage="done",
                                       progress=1.0, run_id=r["run_id"])
            except Exception as e:
                self.ctx.db.update_job(job_id, status="failed", error=str(e))

        self.pool.submit(_run)
        return job_id
