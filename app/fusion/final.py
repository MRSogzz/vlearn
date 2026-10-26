"""最終總結：有 strong 模型則 LLM 融合，否則模板拼接。"""
from __future__ import annotations

import json

from app.context import AppContext
from app.summarize.prompts import SYSTEM_FINAL


def _fmt_ts(sec: float) -> str:
    s = int(sec)
    return f"{s // 60:02d}:{s % 60:02d}"


def render_final(ctx: AppContext, run_id: str, video: dict,
                 bundles: list[dict], summaries_by_id: dict[str, dict],
                 conflicts: list[dict], *, use_llm: bool = True) -> tuple[str, list[str]]:
    unresolved = [c["id"] for c in conflicts if c["status"] == "unresolved"]

    if use_llm and ctx.router.available("final_summary"):
        ctx_payload = {
            "video": {"title": video["title"], "duration": video["duration"]},
            "bundles": [
                {"time_range": b["time_range"], "status": b["status"],
                 "summaries": [summaries_by_id[sid] for sid in b["summary_ids"]
                               if sid in summaries_by_id]}
                for b in bundles
            ],
            "conflicts": conflicts,
        }
        prompt = "已排序的交錯證據：\n" + json.dumps(ctx_payload, ensure_ascii=False)
        resp = ctx.router.call("final_summary", run_id,
                               messages=[{"role": "system", "content": SYSTEM_FINAL},
                                         {"role": "user", "content": prompt}],
                               max_tokens=2000)
        if resp:
            return resp, unresolved

    # 模板拼接（本地降級）
    lines = [f"# {video['title']}", ""]
    lines.append(f"- 視頻 ID：`{video['video_id']}`")
    lines.append(f"- 時長：{_fmt_ts(video['duration'])}")
    lines.append("")

    # ---------- 核心內容（summary 原文） ----------
    lines.append("## 核心內容")
    lines.append("")
    for b in bundles:
        lo, hi = b["time_range"]
        parts = []
        for sid in b["summary_ids"]:
            s = summaries_by_id.get(sid)
            if not s:
                continue
            parts.append(f"- [{s.get('source_type')}] {s.get('summary', '')}")
        if parts:
            lines.append(f"### {_fmt_ts(lo)} – {_fmt_ts(hi)}")
            lines.extend(parts)
            lines.append("")

    # ---------- 關鍵時間點（可校驗斷言） ----------
    lines.append("## 關鍵時間點（可校驗斷言）")
    lines.append("")
    has_assertions = False
    for b in bundles:
        lo, hi = b["time_range"]
        bundle_asserts: list[dict] = []
        seen_claims: set[str] = set()
        for sid in b["summary_ids"]:
            s = summaries_by_id.get(sid)
            if not s:
                continue
            for a in s.get("assertions", []):
                claim = (a.get("claim") or "").strip()
                if not claim or claim in seen_claims:
                    continue
                seen_claims.add(claim)
                bundle_asserts.append(a)
        if not bundle_asserts:
            continue
        has_assertions = True
        lines.append(f"### {_fmt_ts(lo)} – {_fmt_ts(hi)}")
        for a in bundle_asserts:
            kind = a.get("kind", "other")
            claim = a.get("claim", "")
            ref = a.get("ref", "")
            ref_suffix = f" `{ref}`" if ref else ""
            lines.append(f"- [{kind}] {claim}{ref_suffix}")
        lines.append("")
    if not has_assertions:
        lines.append("- （無斷言抽取，可能是純視覺內容或字幕過短）")
        lines.append("")

    # ---------- 不確定 / 未解決 ----------
    lines.append("## 不確定 / 未解決")
    if not unresolved:
        lines.append("- 無")
    else:
        for c in conflicts:
            if c["status"] == "unresolved":
                srcs = ", ".join(c.get("sources", []))
                lines.append(f"- `{c['id']}` {srcs}：{c.get('reason', '')}（保留雙版本）")
    lines.append("")

    # ---------- 來源說明 ----------
    lines.append("## 來源說明")
    lines.append("- 官方字幕：平臺字幕 API")
    lines.append("- 關鍵幀：FFmpeg 場景檢測 + 右邊界截斷")
    lines.append("- 彈幕/評論（如存在）：僅供觀眾反應參考")
    lines.append("")
    lines.append("> 事實/觀點/觀眾反應/AI 推測已在各段來源標註。")

    return "\n".join(lines), unresolved
