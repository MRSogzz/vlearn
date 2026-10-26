"""初篩：純文本，不讀圖。輸出 worth_reading / not_worth / uncertain。"""
from __future__ import annotations

from app.context import AppContext


def triage(ctx: AppContext, video_id: str, *, run_id: str = "triage") -> dict:
    video = ctx.db.get_video(video_id)
    if not video:
        return {"verdict": "uncertain", "reason": "video not found"}
    cfg = ctx.config["triage"]
    subs = ctx.db.segments(video_id, "official_subtitle")
    text = " ".join(s["text"] for s in subs)
    chars = len(text)
    dur = float(video["duration"])

    # 硬性門檻（本地啟發式）
    if not cfg["enabled"]:
        verdict, reason = "worth_reading", "triage disabled"
    elif dur < cfg["min_duration_sec"] and chars < cfg["min_subtitle_chars"]:
        verdict, reason = "not_worth", f"duration {dur:.0f}s + subtitle {chars} chars below thresholds"
    elif chars < cfg["min_subtitle_chars"]:
        verdict, reason = "uncertain", f"only {chars} subtitle chars"
    else:
        verdict, reason = "worth_reading", f"duration {dur:.0f}s, subtitle {chars} chars"

    # 若模型可用，讓 cheap 模型複核（失敗不阻斷）
    if ctx.router.available("triage") and chars > 0:
        prompt = (
            "判斷這段視頻是否值得深入學習（2-4 分鐘精度）。"
            "只回答 WORTH / NOT_WORTH / UNCERTAIN 之一，然後給出 1 句理由。\n\n"
            f"標題：{video['title']}\n時長：{dur:.0f}s\n字幕節選：{text[:1500]}"
        )
        resp = ctx.router.call("triage", run_id,
                               messages=[{"role": "user", "content": prompt}],
                               max_tokens=80)
        if resp:
            head = resp.strip().split()[0].upper() if resp.strip() else ""
            mapped = {"WORTH": "worth_reading",
                      "NOT_WORTH": "not_worth"}.get(head, "uncertain")
            # 模型只做複核：當本地 verdict 與模型不一致時取保守一方
            if mapped != verdict:
                verdict = "uncertain" if verdict == "worth_reading" else mapped
                reason = f"local={verdict}, llm={head}"
            else:
                reason = f"{reason}; llm confirm {head}"

    ctx.db.save_triage(video_id, verdict, reason)
    return {"video_id": video_id, "verdict": verdict, "reason": reason}
