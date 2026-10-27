"""scripts/evaluate_quality.py — 質量評測工具。

三個子命令：
  traceability    算形式可追溯率（腳本自動）
  export-sample   導出斷言抽樣 CSV，供人工標註實質可追溯率
  compare         對比兩個 run（vision on vs off）

用法：
    # 形式可追溯率
    python scripts/evaluate_quality.py traceability --run-id run_abc123

    # 導出 30 條抽樣到 quality_sample.csv（人工填 verdict 列）
    python scripts/evaluate_quality.py export-sample --run-id run_abc123 --n 30

    # 對比全模態 vs 純字幕
    python scripts/evaluate_quality.py compare --run-a run_full --run-b run_subtitle_only
"""
from __future__ import annotations
import argparse
import csv
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.context import AppContext


# ============================================================
#  1. 形式可追溯率
# ============================================================

def cmd_traceability(ctx: AppContext, run_id: str) -> int:
    report = ctx.db.get_report(run_id)
    if not report:
        print(f"ERROR: report {run_id} not found")
        return 1

    video_id = report["video_id"]
    assertions = json.loads(report["assertions"])
    if not assertions:
        print(f"report {run_id} has 0 assertions")
        return 1

    segment_ids = {s["id"] for s in ctx.db.segments(video_id)}
    keyframe_ids = {k["id"] for k in ctx.db.keyframes(video_id)}
    all_refs = segment_ids | keyframe_ids

    total = len(assertions)
    with_ref = 0
    with_time = 0
    ref_valid = 0
    by_source = Counter()
    invalid_refs: list[str] = []
    missing_refs: list[str] = []

    for a in assertions:
        ref = a.get("ref", "")
        tr = a.get("time_range")
        src = a.get("source_type", "?")
        by_source[src] += 1

        if ref:
            with_ref += 1
        if tr and len(tr) == 2 and tr[1] > tr[0]:
            with_time += 1

        if ref in all_refs:
            ref_valid += 1
        elif ref:
            invalid_refs.append(ref)
        else:
            missing_refs.append(a.get("claim", "")[:60])

    print(f"run:   {run_id}")
    print(f"video: {video_id}")
    print(f"total: {total} assertions")
    print()
    print("by source:")
    for src, n in by_source.most_common():
        print(f"  {src:20s} {n:4d}  ({n/total*100:5.1f}%)")
    print()
    print("形式可追溯率（腳本可測）:")
    print(f"  有 ref:            {with_ref:4d}/{total}  ({with_ref/total*100:5.1f}%)")
    print(f"  有 time_range:     {with_time:4d}/{total}  ({with_time/total*100:5.1f}%)")
    print(f"  ref 指向 DB 證據:  {ref_valid:4d}/{total}  ({ref_valid/total*100:5.1f}%)")
    print()

    if invalid_refs:
        print(f"⚠ 無效 ref ({len(invalid_refs)} 條，前 5 條):")
        for r in invalid_refs[:5]:
            print(f"    {r}")
    if missing_refs:
        print(f"⚠ 缺 ref ({len(missing_refs)} 條，前 5 條):")
        for c in missing_refs[:5]:
            print(f"    {c}")

    print()
    print("注意：這只是「形式」可追溯率。")
    print("要測「實質」可追溯率（ref 是否真的支持 claim），跑:")
    print(f"    python scripts/evaluate_quality.py export-sample --run-id {run_id} --n 30")
    return 0


# ============================================================
#  2. 導出抽樣 CSV 供人工標註
# ============================================================

def cmd_export_sample(ctx: AppContext, run_id: str, n: int) -> int:
    report = ctx.db.get_report(run_id)
    if not report:
        print(f"ERROR: report {run_id} not found")
        return 1

    video_id = report["video_id"]
    assertions = json.loads(report["assertions"])
    if not assertions:
        print(f"report {run_id} has 0 assertions")
        return 1

    # 建立 ref -> 原文/畫面描述的索引
    seg_text = {s["id"]: s["text"] for s in ctx.db.segments(video_id)}
    kf_desc = {}  # keyframe 的 ref 對應它的斷言（因為 keyframe 本身沒"原文"）

    # 從斷言本身反推 keyframe 的描述：同一 ref 的多條斷言合併
    for a in assertions:
        ref = a.get("ref", "")
        if ref.startswith("kf_"):
            kf_desc.setdefault(ref, []).append(a.get("claim", ""))

    # 隨機抽樣
    random.seed(42)  # 可復現
    sample_size = min(n, len(assertions))
    sampled = random.sample(assertions, sample_size)

    out_path = Path(f"quality_sample_{run_id}.csv")
    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "idx",
            "claim",
            "kind",
            "source_type",
            "ref",
            "time_range",
            "evidence",           # ref 對應的原文/畫面描述
            "verdict",            # 人工填：correct / wrong / vague / unsupported
            "notes",              # 人工填
        ])

        for i, a in enumerate(sampled, 1):
            ref = a.get("ref", "")
            if ref in seg_text:
                evidence = seg_text[ref]
            elif ref in kf_desc:
                evidence = " | ".join(kf_desc[ref])
            else:
                evidence = f"(ref {ref} not found in DB)"

            tr = a.get("time_range", [0, 0])
            writer.writerow([
                i,
                a.get("claim", ""),
                a.get("kind", ""),
                a.get("source_type", ""),
                ref,
                f"{tr[0]:.1f}-{tr[1]:.1f}" if len(tr) == 2 else "",
                evidence[:300],
                "",  # 待人工填
                "",
            ])

    print(f"exported {sample_size}/{len(assertions)} assertions to: {out_path}")
    print()
    print("下一步：")
    print(f"  1. 打開 {out_path}")
    print("  2. 逐行對照 evidence 列，在 verdict 列填：")
    print("     - correct      證據確實支持 claim")
    print("     - wrong        證據和 claim 矛盾")
    print("     - vague        claim 太抽象，無法核實")
    print("     - unsupported  證據裡找不到相關信息")
    print("  3. 統計 verdict 分佈:")
    print(f"     python scripts/evaluate_quality.py summarize-sample --csv {out_path}")
    return 0


# ============================================================
#  3. 彙總人工標註結果
# ============================================================

def cmd_summarize_sample(csv_path: str) -> int:
    path = Path(csv_path)
    if not path.exists():
        print(f"ERROR: {path} not found")
        return 1

    counts: Counter = Counter()
    total = 0
    with path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            v = (row.get("verdict") or "").strip().lower()
            if not v:
                continue
            counts[v] += 1
            total += 1

    if total == 0:
        print("no verdicts filled yet")
        return 1

    print(f"sample size: {total}")
    print("verdict distribution:")
    for v, n in counts.most_common():
        print(f"  {v:12s} {n:4d}  ({n/total*100:5.1f}%)")

    correct = counts.get("correct", 0)
    wrong = counts.get("wrong", 0)
    vague = counts.get("vague", 0)
    unsupported = counts.get("unsupported", 0)

    print()
    print(f"實質可追溯率（correct / total）: {correct}/{total} = {correct/total*100:.1f}%")
    print(f"錯誤率（wrong / total）:         {wrong}/{total} = {wrong/total*100:.1f}%")
    print(f"模糊率（vague / total）:         {vague}/{total} = {vague/total*100:.1f}%")
    print(f"不支持率（unsupported / total）: {unsupported}/{total} = {unsupported/total*100:.1f}%")
    return 0


# ============================================================
#  4. 對比兩個 run（vision on vs off）
# ============================================================

def cmd_compare(ctx: AppContext, run_a: str, run_b: str) -> int:
    ra = ctx.db.get_report(run_a)
    rb = ctx.db.get_report(run_b)
    if not ra or not rb:
        print("ERROR: one or both reports not found")
        return 1

    arr_a = json.loads(ra["assertions"])
    arr_b = json.loads(rb["assertions"])

    def stats(arr):
        by = Counter(a.get("source_type", "?") for a in arr)
        kinds = Counter(a.get("kind", "?") for a in arr)
        return len(arr), dict(by), dict(kinds)

    n_a, src_a, kind_a = stats(arr_a)
    n_b, src_b, kind_b = stats(arr_b)

    print(f"run A: {run_a}  ({ra['video_id']})")
    print(f"  total: {n_a}")
    print(f"  by source: {src_a}")
    print(f"  by kind:   {kind_a}")
    print()
    print(f"run B: {run_b}  ({rb['video_id']})")
    print(f"  total: {n_b}")
    print(f"  by source: {src_b}")
    print(f"  by kind:   {kind_b}")
    print()

    conflicts_a = len(ctx.db.list_conflicts(run_a, only_unresolved=False))
    conflicts_b = len(ctx.db.list_conflicts(run_b, only_unresolved=False))
    print(f"衝突數:  A={conflicts_a}  B={conflicts_b}")
    print()
    print("提示：")
    print("  - 若 A 有 keyframe_vlm 而 B 沒有，說明差異來自圖片管線")
    print("  - 若 A 的衝突數 > B，說明圖片管線檢出了字幕看不到的矛盾")
    print("  - 若 A 斷言數 >> B，需人工抽樣檢查 A 的額外斷言是否可信")
    return 0


# ============================================================
#  CLI
# ============================================================

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config/default.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("traceability")
    s.add_argument("--run-id", required=True)

    s = sub.add_parser("export-sample")
    s.add_argument("--run-id", required=True)
    s.add_argument("--n", type=int, default=30)

    s = sub.add_parser("summarize-sample")
    s.add_argument("--csv", required=True)

    s = sub.add_parser("compare")
    s.add_argument("--run-a", required=True)
    s.add_argument("--run-b", required=True)

    args = p.parse_args()

    if args.cmd == "summarize-sample":
        return cmd_summarize_sample(args.csv)

    ctx = AppContext.from_config(args.config)

    if args.cmd == "traceability":
        return cmd_traceability(ctx, args.run_id)
    if args.cmd == "export-sample":
        return cmd_export_sample(ctx, args.run_id, args.n)
    if args.cmd == "compare":
        return cmd_compare(ctx, args.run_a, args.run_b)
    return 0


if __name__ == "__main__":
    sys.exit(main())
