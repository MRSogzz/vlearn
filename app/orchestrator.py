"""統一管道：CLI 與 MCP 共用。"""
from __future__ import annotations

import uuid
from pathlib import Path

from app.context import AppContext
from app.cost.budget import RuntimeProfile
from app.evidence.arbiter import arbitrate
from app.evidence.bundle import build_bundles
from app.evidence.consistency import check_bundle
from app.fusion.final import render_final
from app.fusion.interleave import interleave
from app.ingest.pipeline import ingest_url
from app.keyframes.fallback import extract_frame, fixed_interval_points, phash_dedup
from app.keyframes.scene import detect_scene_points, measure_sharpness
from app.keyframes.selector import select_keyframes_dispatch
from app.render.markdown import render_report
from app.schemas import EvidenceBundle, SourceType
from app.summarize.local import summarize_window
from app.triage.triage import triage


class Orchestrator:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    # ---------- ingest ----------
    def ingest(self, url: str, platform: str = "youtube") -> dict:
        return ingest_url(self.ctx, url, platform)

    # ---------- analyze（同步） ----------
    def analyze(self, video_id: str, profile: str = "standard",
                _progress=None) -> dict:
        ctx = self.ctx
        cfg = ctx.config
        kf = cfg["keyframes"]
        sm = cfg["summary"]

        run_id = f"run_{uuid.uuid4().hex[:10]}"
        video = ctx.db.get_video(video_id)
        if not video:
            raise ValueError(f"video {video_id} not found")

        profile_rt = RuntimeProfile(
            vision_policy=cfg["vision"]["policy"],
            max_backtracks=cfg["evidence"]["max_backtracks"],
            batch_windows=sm["batch_windows"],
        )

        if _progress:
            _progress("triage", 0.05)

        # 1) 初篩
        tri = triage(ctx, video_id, run_id=run_id)
        if tri["verdict"] == "not_worth":
            subs = ctx.db.segments(video_id, "official_subtitle")
            text = " ".join(s["text"] for s in subs)
            md = (f"# {video['title']}\n\n"
                  f"> 初篩：not_worth（{tri['reason']}）。以下為輕量文字摘要。\n\n"
                  f"{text[:1200]}")
            path = render_report(md, cfg["output"]["output_dir"], run_id)
            ctx.db.save_report(run_id, video_id, md, [], [])
            return {"run_id": run_id, "video_id": video_id,
                    "verdict": "not_worth", "path": path}

        if _progress:
            _progress("keyframes", 0.10)

        # 2) 關鍵幀窗口選擇（dispatcher）
        scene_points: list[float] = []
        media_path = None
        meta_obj = None
        try:
            adapter = ctx.adapter_for(video["platform"])
            from app.adapters.base import VideoMeta
            meta_obj = VideoMeta(
                video_id=video_id, platform=video["platform"],
                url=video["url"], title=video["title"],
                duration=float(video["duration"]),
                author=video.get("author", ""),
                description=video.get("description", ""),
            )
            media_path = adapter.download_media(meta_obj)
        except Exception:
            meta_obj = None
            media_path = None

        if media_path:
            scene_points = detect_scene_points(media_path, kf["scene_threshold"])
        if kf["fallback_enabled"]:
            scene_points += fixed_interval_points(
                float(video["duration"]), kf["fixed_interval_sec"],
                cap=kf["max_frames_per_10min"] * 4,
                per_10min=kf["max_frames_per_10min"])

        mode = "frame_exact" if media_path else "seek"
        selected = select_keyframes_dispatch(
            scene_points, float(video["duration"]),
            mode=mode,
            fps=kf["fps_assumption"],
            max_window_sec=kf["max_window_sec"],
            min_gap_sec=kf["min_gap_sec"],
            right_margin_sec=0.4,
            frame_scores=self._frame_scores(media_path, scene_points, kf),
        )

        # 兜底 kf_rows（完整下載模式下用 extract_frame 抽本地幀）
        frames_out = Path(cfg["output"]["output_dir"]) / "frames" / video_id
        fallback_kf_rows: list[dict] = []
        fallback_frame_paths: list[str] = []
        for f in selected:
            p = extract_frame(media_path, f.chosen_ts, str(frames_out)) if media_path else None
            if p:
                fallback_frame_paths.append(p)
            fallback_kf_rows.append({
                "id": f"kf_{uuid.uuid4().hex[:8]}",
                "video_id": video_id,
                "timestamp": f.chosen_ts,
                "trigger_type": f.trigger_type,
                "sharpness": 0.0,
                "image_path": p,
                "quality_flags": [],
            })
        if fallback_frame_paths:
            kept = set(phash_dedup(fallback_frame_paths, kf["phash_dedup_threshold"]))
            for r in fallback_kf_rows:
                if r["image_path"] and r["image_path"] not in kept:
                    r["image_path"] = None

        # 不立即寫入 keyframes 表——等圖片 pipeline 完成後決定用哪套記錄

        if _progress:
            _progress("summary", 0.20)

        # 3) 字幕局部摘要（按關鍵時間段窗口）
        if selected:
            window_bounds = [(f.window_start, f.window_end) for f in selected]
        else:
            dur = float(video["duration"])
            window_bounds = [(i * 60.0, min(i * 60.0 + 60.0, dur))
                             for i in range(int(dur // 60) + 1)]

        subs = ctx.db.segments(video_id, "official_subtitle")
        summaries: list[dict] = []
        for (lo, hi) in window_bounds:
            window_subs = [s for s in subs if s["start"] < hi and s["end"] > lo]
            if not window_subs:
                continue

            combined_text = " ".join(s["text"] for s in window_subs)
            first_ref = window_subs[0]["id"]

            r = summarize_window(
                ctx, run_id, video_id,
                time_range=(lo, hi),
                text=combined_text,
                ref=first_ref,
                source_type="official_subtitle",
                max_chars=sm["window_max_chars"],
            )

            summaries.append({
                "id": f"ws_{uuid.uuid4().hex[:8]}",
                "video_id": video_id,
                "time_range": (lo, hi),
                "source_type": "official_subtitle",
                "summary": r["summary"],
                "assertions": r["assertions"],
                "raw_ref": first_ref,
            })

        # 3.5) 圖片 pipeline（獨立運行，與字幕 summaries 合流）
        image_frame_count = 0
        image_class = "skipped"
        img_result = None
        if meta_obj and profile_rt.vision_policy != "none":
            if _progress:
                _progress("image_probe", 0.30)
            try:
                from app.keyframes.pipeline import run_image_pipeline

                def _img_progress(stage: str, pct: float):
                    if _progress:
                        _progress(f"image_{stage}", 0.30 + pct * 0.20)

                img_result = run_image_pipeline(
                    ctx, run_id, video_id, meta_obj, subs,
                    _progress=_img_progress,
                )
                if img_result.summaries:
                    summaries.extend(img_result.summaries)
                image_frame_count = img_result.frames_used
                image_class = img_result.class_result.video_class
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    "image pipeline failed: %s", e, exc_info=True)
                img_result = None

        # 寫入 keyframes 表：優先用圖片 pipeline 的真實幀，否則用兜底空殼
        if img_result and img_result.frames_meta:
            final_kf_rows = [
                {
                    "id": fm["id"],
                    "video_id": video_id,
                    "timestamp": fm["timestamp"],
                    "trigger_type": fm["trigger_type"],
                    "sharpness": 0.0,
                    "image_path": fm["image_path"],
                    "quality_flags": [],
                }
                for fm in img_result.frames_meta
            ]
        else:
            final_kf_rows = fallback_kf_rows

        # ★ 清空該 video_id 的舊 keyframes，避免歷史累積（每次 analyze 冪等）
        ctx.db.clear_keyframes(video_id)
        ctx.db.insert_keyframes(final_kf_rows)

        # 跨源去重：同源內去重，跨源保留（多源交叉驗證的機會）
        seen_by_source: dict[str, set[str]] = {}
        for s in summaries:
            src = s.get("source_type", "unknown")
            seen = seen_by_source.setdefault(src, set())
            filtered: list[dict] = []
            for a in s["assertions"]:
                key = (a.get("claim") or "").lower().strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                filtered.append(a)
            s["assertions"] = filtered

        # 預算檢查 → 觸發降級
        if ctx.budget.should_degrade(run_id) and ctx.budget.on_exceed() == "degrade":
            profile_rt.apply("vision.policy", "none")
            profile_rt.apply("evidence.max_backtracks", 0)

        if _progress:
            _progress("evidence", 0.55)

        # 4) 證據束 + 一致性
        summaries_by_id = {s["id"]: s for s in summaries}
        bundles = build_bundles(video_id, summaries)
        conflicts: list[dict] = []
        for b in bundles:
            verdict = check_bundle(b, summaries_by_id)
            b["status"] = "conflict" if verdict == "conflict" else \
                          "suspect" if verdict == "suspect" else "consistent"
            if b["status"] in ("conflict", "suspect"):
                conflict = self._arbitrate_bundle(b, summaries_by_id)
                conflict["bundle_id"] = b["id"]
                conflict["run_id"] = run_id
                conflict["raw_payload"] = {"time_range": list(b["time_range"])}
                conflicts.append(conflict)

        # 5) 衝突回溯（受 max_backtracks 限制）
        if profile_rt.max_backtracks > 0:
            from app.backtrace.backtrace import backtrace
            bt_budget = profile_rt.max_backtracks
            for c, b in zip([cf for cf in conflicts if cf["status"] == "unresolved"], bundles, strict=False):
                if bt_budget <= 0:
                    break
                if c.get("bundle_id") != b["id"]:
                    continue
                bt = backtrace(ctx, run_id, video_id, tuple(b["time_range"]))
                c["raw_payload"] = {**c.get("raw_payload", {}), "backtrace": bt}
                bt_budget -= 1

        ctx.db.save_conflicts(run_id, conflicts)

        if _progress:
            _progress("render", 0.85)

        # 6) 融合 + 最終總結
        interleave(video, bundles, summaries_by_id, conflicts)
        final_md, unresolved = render_final(
            ctx, run_id, video, bundles, summaries_by_id, conflicts,
            use_llm=True)

        # 7) 渲染 + 修正
        path = render_report(final_md, cfg["output"]["output_dir"], run_id)
        ctx.db.save_report(run_id, video_id, final_md,
                           assertions=[a for s in summaries for a in s["assertions"]],
                           unresolved=unresolved)

        if _progress:
            _progress("done", 1.0)

        return {"run_id": run_id, "video_id": video_id, "path": path,
                "bundles": len(bundles), "conflicts": len(conflicts),
                "unresolved": len(unresolved),
                "image_class": image_class,
                "image_frames": image_frame_count,
                "cost_usd": round(ctx.ledger.run_spend(run_id), 6)}

    # ---------- helpers ----------
    def _frame_scores(self, media_path, scene_points, kf) -> dict[float, float] | None:
        if not media_path or not kf.get("sharpness_enabled"):
            return None
        scores: dict[float, float] = {}
        for t in scene_points:
            scores[t] = measure_sharpness(media_path, t)
        return scores or None

    def _arbitrate_bundle(self, bundle: dict, summaries_by_id: dict) -> dict:
        members = [summaries_by_id[sid] for sid in bundle["summary_ids"]
                   if sid in summaries_by_id]
        items = []
        for m in members:
            st = m.get("source_type")
            try:
                st_enum = SourceType(st) if isinstance(st, str) else st
            except ValueError:
                st_enum = SourceType.KEYFRAME
            items.append({
                "source_type": st_enum,
                "confidence": 1.0,
                "quality_flags": [],
                "claim": m.get("summary", ""),
            })
        b_model = EvidenceBundle(
            id=bundle["id"], video_id=bundle["video_id"],
            time_range=tuple(bundle["time_range"]),
            summary_ids=bundle["summary_ids"], status="conflict")
        record = arbitrate(b_model, items)
        return {
            "id": record.id, "bundle_id": record.bundle_id,
            "sources": record.sources, "status": record.status,
            "adopted_source": record.adopted_source, "reason": record.reason,
            "confidence": record.confidence,
            "keep_both_versions": record.keep_both_versions,
        }
