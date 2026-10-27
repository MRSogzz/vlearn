"""scripts/evaluate_batch.py — 批量跑 traceability + 彙總 markdown 表格。

用法：
    python scripts/evaluate_batch.py --video-ids 8S0FDjFBj8o qp0HIF3SfI4 dQw4w9WgXcQ
    python scripts/evaluate_batch.py --all
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.context import AppContext
from app.orchestrator import Orchestrator


def run_one(ctx: AppContext, video_id: str) -> dict | None:
    video = ctx.db.get_video(video_id)
    if not video:
        print(f"[SKIP] {video_id} not ingested")
        return None

    print(f"\n{'='*70}")
    print(f"[RUN] {video_id} — {video['title'][:60]}")
    print(f"      duration: {video['duration']:.0f}s")
    print(f"{'='*70}")

    try:
        result = Orchestrator(ctx).analyze(video_id)
    except Exception as e:
        print(f"[FAIL] analyze: {type(e).__name__}: {e}")
        return None

    run_id = result["run_id"]
    report = ctx.db.get_report(run_id)
    assertions = json.loads(report["assertions"])

    segment_ids = {s["id"] for s in ctx.db.segments(video_id)}
    keyframe_ids = {k["id"] for k in ctx.db.keyframes(video_id)}
    all_refs = segment_ids | keyframe_ids

    total = len(assertions)
    with_ref = sum(1 for a in assertions if a.get("ref"))
    with_time = sum(1 for a in assertions
                    if a.get("time_range") and len(a["time_range"]) == 2
                    and a["time_range"][1] > a["time_range"][0])
    ref_valid = sum(1 for a in assertions if a.get("ref") in all_refs)

    from collections import Counter
    by_source = Counter(a.get("source_type", "?") for a in assertions)

    print(f"\n[OK] run_id: {run_id}")
    print(f"     assertions: {total}")
    print(f"     by source:  {dict(by_source)}")
    print(f"     traceability:")
    print(f"       ref:      {with_ref}/{total} ({with_ref/total*100:.1f}%)")
    print(f"       time:     {with_time}/{total} ({with_time/total*100:.1f}%)")
    print(f"       ref→DB:   {ref_valid}/{total} ({ref_valid/total*100:.1f}%)")

    return {
        "video_id": video_id,
        "title": video["title"],
        "duration_sec": video["duration"],
        "run_id": run_id,
        "total": total,
        "by_source": dict(by_source),
        "with_ref": with_ref,
        "with_time": with_time,
        "ref_valid": ref_valid,
        "bundles": result.get("bundles", 0),
        "conflicts": result.get("conflicts", 0),
        "image_frames": result.get("image_frames", 0),
    }


def render_markdown(results: list[dict]) -> str:
    lines = [
        "| Video | Duration | Assertions | subtitle | keyframe | ref | time | ref→DB |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        src = r["by_source"]
        lines.append(
            f"| `{r['video_id']}` | "
            f"{int(r['duration_sec'])//60}:{int(r['duration_sec'])%60:02d} | "
            f"{r['total']} | "
            f"{src.get('official_subtitle', 0)} | "
            f"{src.get('keyframe_vlm', 0)} | "
            f"{r['with_ref']}/{r['total']} | "
            f"{r['with_time']}/{r['total']} | "
            f"{r['ref_valid']}/{r['total']} |"
        )
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config/default.yaml")
    p.add_argument("--video-ids", nargs="+")
    p.add_argument("--all", action="store_true",
                   help="run all videos in DB")
    args = p.parse_args()

    ctx = AppContext.from_config(args.config)

    if args.all:
        videos = ctx.db.list_videos(100)
        video_ids = [v["video_id"] for v in videos]
    elif args.video_ids:
        video_ids = args.video_ids
    else:
        print("ERROR: pass --video-ids or --all")
        return 1

    print(f"running {len(video_ids)} video(s)...")

    results = []
    for vid in video_ids:
        r = run_one(ctx, vid)
        if r:
            results.append(r)

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(render_markdown(results))
    print()

    # 保存 markdown 供 README 用
    out = Path("quality_batch.md")
    out.write_text(render_markdown(results) + "\n", encoding="utf-8")
    print(f"saved to: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
