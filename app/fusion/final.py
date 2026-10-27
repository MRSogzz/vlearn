"""最終總結：有 strong 模型則 LLM 融合，否則模板拼接。

模板路徑加了一層「全域概覽」：用已有分段摘要拼成 prompt，調
final_summary（優先）或 local_summary（降級）生成 2-4 句影片核心內容概覽。

關鍵設計：
- **預設繁體中文** —— prompt 和模板文本都是繁體中文
- **保留全部摘要** —— 不截斷，確保覆蓋影片起止
- **max_tokens=1500** —— 給 4B 的 reasoning 留空間
- **失敗 fallback 用首尾摘要合併** —— 比只返回第一段更完整
- content 空時 router 會從 reasoning_content 搶救
"""
from __future__ import annotations
import json
import logging

from app.context import AppContext
from app.summarize.prompts import SYSTEM_FINAL

log = logging.getLogger(__name__)


def _fmt_ts(sec: float) -> str:
    s = int(sec)
    return f"{s // 60:02d}:{s % 60:02d}"


def _generate_overview(
    ctx: AppContext, run_id: str, video: dict, summaries: list[dict]
) -> str | None:
    """用 LLM 生成 2-4 句全域概覽（繁體中文）。

    保留全部摘要（不截斷）——13 條 × 200 字 = 2600 字，遠低於 4B context。
    """
    if not summaries:
        return None

    parts = []
    for s in summaries:
        if not s.get("summary"):
            continue
        lo, hi = s.get("time_range", (0, 0))
        parts.append(f"[{_fmt_ts(lo)}-{_fmt_ts(hi)}] {s['summary']}")
    if not parts:
        return None

    all_summaries = "\n".join(parts)

    # 繁體中文 prompt，明確要求繁體中文輸出
    prompt = (
        f"請根據以下影片分段摘要，用 2-4 句話概括整個影片的核心主題和要點。"
        f"要具體，不要寫「影片講了...」這類套話。"
        f"輸出語言：繁體中文。\n\n"
        f"影片標題：{video['title']}\n\n"
        f"分段摘要（按時間排序）：\n{all_summaries}\n\n"
        f"概覽："
    )

    stage = None
    if ctx.router.available("final_summary"):
        stage = "final_summary"
    elif ctx.router.available("local_summary"):
        stage = "local_summary"

    if stage is None:
        log.warning("no LLM stage available; using first+last summary")
        first = summaries[0].get("summary", "").strip()
        last = summaries[-1].get("summary", "").strip()
        combined = (first + " ... " + last) if len(summaries) > 1 else first
        return combined[:300] if combined else None

    resp = None
    try:
        resp = ctx.router.call(
            stage, run_id,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
            temperature=0.3,
        )
        log.info(
            "overview LLM call: stage=%s resp_type=%s resp_len=%s prompt_len=%s",
            stage,
            type(resp).__name__,
            len(resp) if resp else 0,
            len(prompt),
        )
    except Exception as e:
        log.warning("overview LLM call raised: %s", e, exc_info=True)

    if resp and resp.strip():
        text = resp.strip()
        for prefix in ("Sure,", "Here", "Overview:", "Summary:",
                       "概覽：", "摘要：", "以下是"):
            if text.lower().startswith(prefix.lower()):
                text = text[len(prefix):].strip()
        if text:
            return text

    log.warning("overview LLM returned empty (resp=%r); fallback to first+last", resp)
    first = summaries[0].get("summary", "").strip()
    last = summaries[-1].get("summary", "").strip()
    if len(summaries) > 1:
        return (first + " ... " + last)[:300]
    return first[:300] if first else None


def render_final(ctx: AppContext, run_id: str, video: dict,
                 bundles: list[dict], summaries_by_id: dict[str, dict],
                 conflicts: list[dict], *, use_llm: bool = True) -> tuple[str, list[str]]:
    unresolved = [c["id"] for c in conflicts if c["status"] == "unresolved"]

    # 路徑 A：strong 模型存在，走完整 LLM 融合
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

    # 路徑 B：模板拼接（繁體中文）
    lines = [f"# {video['title']}", ""]
    lines.append(f"- 影片 ID：`{video['video_id']}`")
    lines.append(f"- 時長：{_fmt_ts(video['duration'])}")
    lines.append("")

    # ---------- 全域概覽 ----------
    if use_llm:
        all_summaries = [
            summaries_by_id[sid]
            for b in bundles
            for sid in b["summary_ids"]
            if sid in summaries_by_id
        ]
        overview = _generate_overview(ctx, run_id, video, all_summaries)
        if overview:
            lines.append("## 概覽")
            lines.append("")
            lines.append(overview)
            lines.append("")

    # ---------- 核心內容 ----------
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

    # ---------- 關鍵時間點 ----------
    lines.append("## 關鍵時間點")
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
        lines.append("- （無斷言抽取）")
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
    lines.append("- 官方字幕：平台字幕 API")
    lines.append("- 關鍵幀：FFmpeg 場景檢測 + 右邊界截斷")
    lines.append("- 彈幕/評論（如存在）：僅供觀眾反應參考")
    lines.append("")
    lines.append("> 事實/觀點/觀眾反應/AI 推測已在各段來源標註。")

    return "\n".join(lines), unresolved