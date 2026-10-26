from __future__ import annotations

import csv
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    video_id    TEXT PRIMARY KEY,
    platform    TEXT NOT NULL,
    url         TEXT NOT NULL,
    title       TEXT NOT NULL,
    duration    REAL NOT NULL,
    author      TEXT DEFAULT '',
    description TEXT DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS segments (
    id            TEXT PRIMARY KEY,
    video_id      TEXT NOT NULL,
    source_type   TEXT NOT NULL,
    start         REAL NOT NULL,
    end           REAL NOT NULL,
    text          TEXT DEFAULT '',
    confidence    REAL DEFAULT 1.0,
    reliability   INTEGER DEFAULT 3,
    quality_flags TEXT DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_segments_video ON segments(video_id);
CREATE TABLE IF NOT EXISTS keyframes (
    id            TEXT PRIMARY KEY,
    video_id      TEXT NOT NULL,
    timestamp     REAL NOT NULL,
    trigger_type  TEXT NOT NULL,
    sharpness     REAL DEFAULT 0.0,
    image_path    TEXT,
    quality_flags TEXT DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_keyframes_video ON keyframes(video_id);
CREATE TABLE IF NOT EXISTS reports (
    run_id      TEXT PRIMARY KEY,
    video_id    TEXT NOT NULL,
    report_md   TEXT NOT NULL,
    assertions  TEXT DEFAULT '[]',
    unresolved  TEXT DEFAULT '[]',
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conflicts (
    id             TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL,
    bundle_id      TEXT NOT NULL,
    sources        TEXT DEFAULT '[]',
    status         TEXT NOT NULL,
    adopted_source TEXT,
    reason         TEXT DEFAULT '',
    confidence     TEXT DEFAULT 'medium',
    keep_both      INTEGER DEFAULT 1,
    raw_payload    TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS corrections (
    id         TEXT PRIMARY KEY,
    run_id     TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    old_value  TEXT NOT NULL,
    new_value  TEXT NOT NULL,
    user_note  TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    job_id     TEXT PRIMARY KEY,
    video_id   TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'queued',
    stage      TEXT DEFAULT 'queued',
    progress   REAL DEFAULT 0.0,
    run_id     TEXT,
    error      TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trend (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    url         TEXT DEFAULT '',
    heat        REAL DEFAULT 0.0,
    source      TEXT DEFAULT '',
    imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cost_entries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL,
    provider      TEXT NOT NULL,
    model         TEXT NOT NULL,
    input_tokens  INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    image_tokens  INTEGER DEFAULT 0,
    usd           REAL DEFAULT 0.0,
    is_peak       INTEGER DEFAULT 0,
    stage         TEXT DEFAULT '',
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS triage (
    video_id  TEXT PRIMARY KEY,
    verdict   TEXT NOT NULL,
    reason    TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # ---- videos ----
    def upsert_video(self, meta: dict) -> None:
        with self.conn() as c:
            c.execute(
                """INSERT INTO videos (video_id,platform,url,title,duration,author,description,created_at)
                   VALUES (:video_id,:platform,:url,:title,:duration,:author,:description,:created_at)
                   ON CONFLICT(video_id) DO UPDATE SET
                       title=excluded.title, duration=excluded.duration,
                       description=excluded.description""",
                {**meta, "created_at": _now()},
            )

    def get_video(self, video_id: str) -> dict | None:
        with self.conn() as c:
            r = c.execute("SELECT * FROM videos WHERE video_id=?", (video_id,)).fetchone()
            return dict(r) if r else None

    def list_videos(self, limit: int = 20) -> list[dict]:
        with self.conn() as c:
            rows = c.execute("SELECT * FROM videos ORDER BY created_at DESC LIMIT ?",
                             (limit,)).fetchall()
            return [dict(r) for r in rows]

    # ---- segments ----
    def insert_segments(self, segs: list[dict]) -> int:
        if not segs:
            return 0
        with self.conn() as c:
            c.executemany(
                """INSERT OR REPLACE INTO segments
                   (id,video_id,source_type,start,end,text,confidence,reliability,quality_flags)
                   VALUES (:id,:video_id,:source_type,:start,:end,:text,
                           :confidence,:reliability,:quality_flags)""",
                [{**s, "quality_flags": json.dumps(s.get("quality_flags", []))} for s in segs],
            )
        return len(segs)

    def segments(self, video_id: str, source_type: str | None = None) -> list[dict]:
        q = "SELECT * FROM segments WHERE video_id=?"
        args: list[Any] = [video_id]
        if source_type:
            q += " AND source_type=?"
            args.append(source_type)
        q += " ORDER BY start"
        with self.conn() as c:
            rows = c.execute(q, args).fetchall()
            return [{**dict(r), "quality_flags": json.loads(r["quality_flags"])} for r in rows]

    def segment_counts(self, video_id: str) -> dict[str, int]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT source_type, COUNT(*) n FROM segments WHERE video_id=? GROUP BY source_type",
                (video_id,)).fetchall()
            return {r["source_type"]: r["n"] for r in rows}

    # ---- keyframes ----
    def clear_keyframes(self, video_id: str) -> int:
        """刪除某 video_id 的所有 keyframes（analyze 前清空，避免歷史累積）。"""
        with self.conn() as c:
            r = c.execute("DELETE FROM keyframes WHERE video_id=?", (video_id,))
            return r.rowcount

    def insert_keyframes(self, frames: list[dict]) -> int:
        if not frames:
            return 0
        with self.conn() as c:
            c.executemany(
                """INSERT OR REPLACE INTO keyframes
                   (id,video_id,timestamp,trigger_type,sharpness,image_path,quality_flags)
                   VALUES (:id,:video_id,:timestamp,:trigger_type,:sharpness,
                           :image_path,:quality_flags)""",
                [{**f, "quality_flags": json.dumps(f.get("quality_flags", []))} for f in frames],
            )
        return len(frames)

    def keyframes(self, video_id: str) -> list[dict]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT * FROM keyframes WHERE video_id=? ORDER BY timestamp",
                (video_id,)).fetchall()
            return [{**dict(r), "quality_flags": json.loads(r["quality_flags"])} for r in rows]

    # ---- triage ----
    def save_triage(self, video_id: str, verdict: str, reason: str) -> None:
        with self.conn() as c:
            c.execute("INSERT OR REPLACE INTO triage (video_id,verdict,reason,created_at) "
                      "VALUES (?,?,?,?)", (video_id, verdict, reason, _now()))

    def get_triage(self, video_id: str) -> dict | None:
        with self.conn() as c:
            r = c.execute("SELECT * FROM triage WHERE video_id=?", (video_id,)).fetchone()
            return dict(r) if r else None

    # ---- reports ----
    def save_report(self, run_id: str, video_id: str, md: str,
                    assertions: list, unresolved: list) -> None:
        with self.conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO reports (run_id,video_id,report_md,assertions,unresolved,created_at)
                   VALUES (?,?,?,?,?,?)""",
                (run_id, video_id, md, json.dumps(assertions),
                 json.dumps(unresolved), _now()))

    def get_report(self, run_id: str) -> dict | None:
        with self.conn() as c:
            r = c.execute("SELECT * FROM reports WHERE run_id=?", (run_id,)).fetchone()
            return dict(r) if r else None

    # ---- jobs ----
    def create_job(self, job_id: str, video_id: str) -> None:
        with self.conn() as c:
            c.execute("INSERT INTO jobs (job_id,video_id,status,stage,progress,created_at,updated_at) "
                      "VALUES (?,?,'queued','queued',0,?,?)",
                      (job_id, video_id, _now(), _now()))

    def update_job(self, job_id: str, **kw: Any) -> None:
        allowed = {"status", "stage", "progress", "run_id", "error"}
        sets = ", ".join(f"{k}=?" for k in kw if k in allowed)
        vals = [v for k, v in kw.items() if k in allowed]
        if not sets:
            return
        with self.conn() as c:
            c.execute(f"UPDATE jobs SET {sets}, updated_at=? WHERE job_id=?",
                      (*vals, _now(), job_id))

    def get_job(self, job_id: str) -> dict | None:
        with self.conn() as c:
            r = c.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            return dict(r) if r else None

    # ---- conflicts ----
    def save_conflicts(self, run_id: str, conflicts: list[dict]) -> None:
        if not conflicts:
            return
        with self.conn() as c:
            c.executemany(
                """INSERT OR REPLACE INTO conflicts
                   (id,run_id,bundle_id,sources,status,adopted_source,reason,confidence,keep_both,raw_payload)
                   VALUES (:id,:run_id,:bundle_id,:sources,:status,:adopted_source,
                           :reason,:confidence,:keep_both,:raw_payload)""",
                [{**cf, "run_id": run_id,
                  "sources": json.dumps(cf.get("sources", [])),
                  "keep_both": int(cf.get("keep_both_versions", True)),
                  "raw_payload": json.dumps(cf.get("raw_payload", {}))}
                 for cf in conflicts])

    def list_conflicts(self, run_id: str, only_unresolved: bool = True) -> list[dict]:
        q = "SELECT * FROM conflicts WHERE run_id=?"
        if only_unresolved:
            q += " AND status='unresolved'"
        with self.conn() as c:
            rows = c.execute(q, (run_id,)).fetchall()
            return [{**dict(r),
                     "sources": json.loads(r["sources"]),
                     "keep_both_versions": bool(r["keep_both"]),
                     "raw_payload": json.loads(r["raw_payload"])} for r in rows]

    # ---- corrections ----
    def insert_correction(self, run_id: str, ref: str, old: str, new: str,
                          note: str = "") -> str:
        cid = f"corr_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        with self.conn() as c:
            c.execute("INSERT INTO corrections (id,run_id,target_ref,old_value,new_value,user_note,created_at) "
                      "VALUES (?,?,?,?,?,?,?)", (cid, run_id, ref, old, new, note, _now()))
        return cid

    def corrections(self, run_id: str) -> list[dict]:
        with self.conn() as c:
            rows = c.execute("SELECT * FROM corrections WHERE run_id=?", (run_id,)).fetchall()
            return [dict(r) for r in rows]

    # ---- trend ----
    def import_trend_csv(self, path: str) -> int:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(path)
        rows = []
        with p.open(newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                rows.append({
                    "id": r.get("id") or r.get("video_id") or r.get("url", ""),
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "heat": float(r.get("heat", 0) or 0),
                    "source": r.get("source", "csv"),
                })
        if not rows:
            return 0
        with self.conn() as c:
            c.executemany(
                "INSERT OR REPLACE INTO trend (id,title,url,heat,source,imported_at) "
                "VALUES (:id,:title,:url,:heat,:source,:imported_at)",
                [{**r, "imported_at": _now()} for r in rows])
        return len(rows)

    def trend_top(self, n: int = 20) -> list[dict]:
        with self.conn() as c:
            rows = c.execute("SELECT * FROM trend ORDER BY heat DESC LIMIT ?", (n,)).fetchall()
            return [dict(r) for r in rows]

    # ---- cost ----
    def add_cost(self, entry: dict) -> None:
        with self.conn() as c:
            c.execute(
                """INSERT INTO cost_entries
                   (run_id,provider,model,input_tokens,output_tokens,image_tokens,usd,is_peak,stage,created_at)
                   VALUES (:run_id,:provider,:model,:input_tokens,:output_tokens,
                           :image_tokens,:usd,:is_peak,:stage,:created_at)""",
                {**entry, "is_peak": int(entry.get("is_peak", False)),
                 "created_at": _now()})

    def cost_summary(self, daily: bool = True) -> dict:
        with self.conn() as c:
            if daily:
                q = ("SELECT COUNT(*) n, COALESCE(SUM(usd),0) total, "
                     "COALESCE(SUM(input_tokens+output_tokens+image_tokens),0) tokens "
                     "FROM cost_entries WHERE date(created_at)=date('now')")
            else:
                q = ("SELECT COUNT(*) n, COALESCE(SUM(usd),0) total, "
                     "COALESCE(SUM(input_tokens+output_tokens+image_tokens),0) tokens "
                     "FROM cost_entries")
            r = c.execute(q).fetchone()
            return {"entries": r["n"], "total_usd": round(r["total"], 6), "tokens": r["tokens"]}

    def cost_for_run(self, run_id: str) -> float:
        with self.conn() as c:
            r = c.execute("SELECT COALESCE(SUM(usd),0) t FROM cost_entries WHERE run_id=?",
                          (run_id,)).fetchone()
            return float(r["t"])
