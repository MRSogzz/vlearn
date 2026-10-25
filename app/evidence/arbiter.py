"""衝突仲裁：來源可靠性 + 時間精度 + 多源交叉 + 質量降權。

未解決衝突保留雙版本，不強行統一。

來源可靠性排序（FR-05 修正後）：
  official_subtitle(5) = platform_metadata(5)
    > keyframe_ocr(4)        畫面經 OCR 轉錄，對文字/數字可靠
    > keyframe_vlm(3)        畫面經 VLM caption，有幻覺風險
    > asr(2)                 ASR 聽錯詞會扭曲數字
    > danmaku(1) = comment(1)

關鍵判斷：KEYFRAME_VLM 排在 ASR 之上，因為：
  - VLM 幻覺主要是"過度解讀"（說了不存在的大象），但描述的顏色/形狀/位置通常正確
  - ASR 錯誤是"聽錯詞"（"二點五"→"二點無"），會直接扭曲數字斷言
  - 對數字/顏色類斷言，VLM 比 ASR 更可靠
"""
from app.schemas import EvidenceBundle, ConflictRecord, SourceType


RELIABILITY = {
    SourceType.OFFICIAL_SUBTITLE: 5,
    SourceType.PLATFORM_METADATA: 5,
    SourceType.KEYFRAME_OCR: 4,
    SourceType.KEYFRAME_VLM: 3,
    SourceType.KEYFRAME: 3,          # deprecated alias 兜底
    SourceType.ASR: 2,
    SourceType.DANMAKU: 1,
    SourceType.COMMENT: 1,
}


def _reliability_of(s: dict) -> int:
    """從 summary 裡讀 reliability；缺失時按 source_type 查表。"""
    if "reliability" in s and isinstance(s["reliability"], (int, float)):
        return int(s["reliability"])
    st = s.get("source_type")
    if isinstance(st, str):
        try:
            st = SourceType(st)
        except ValueError:
            return 1
    return RELIABILITY.get(st, 1)


def _source_type_name(s: dict) -> str:
    """把 source_type 歸一化為字符串（兼容 Enum 和 str）。"""
    st = s.get("source_type")
    if isinstance(st, SourceType):
        return st.value
    if isinstance(st, str):
        return st
    return "unknown"


def arbitrate(bundle: EvidenceBundle, summaries: list[dict]) -> ConflictRecord:
    """
    summaries: [{source_type, confidence, quality_flags, claim?}]
    返回裁決記錄；無法判定時 status=unresolved 且 keep_both=True。
    """
    if not summaries:
        return ConflictRecord(
            id=f"c_{bundle.id}", bundle_id=bundle.id,
            sources=[], status="unresolved",
            reason="無可用證據",
            confidence="low", keep_both_versions=True,
        )

    # 1) 排除低質量證據（但有 quality_flags 時降權而非丟棄）
    valid = [s for s in summaries if not s.get("quality_flags")]
    if not valid:
        # 全部都有 quality_flags 時，退回全集（避免空判定）
        valid = summaries

    # 2) 按可靠性 + 置信度加權
    def weight(s: dict) -> float:
        return _reliability_of(s) * float(s.get("confidence", 1.0))

    valid = sorted(valid, key=weight, reverse=True)
    top = valid[0]
    second = valid[1] if len(valid) > 1 else None

    # 3) 交叉驗證：若第二來源可靠性接近（≥80%），保留雙版本
    if second and weight(second) >= weight(top) * 0.8:
        return ConflictRecord(
            id=f"c_{bundle.id}", bundle_id=bundle.id,
            sources=[_source_type_name(s) for s in valid],
            status="unresolved",
            reason="多個高可靠來源不一致",
            confidence="medium",
            keep_both_versions=True,
        )

    top_rel = _reliability_of(top)
    return ConflictRecord(
        id=f"c_{bundle.id}", bundle_id=bundle.id,
        sources=[_source_type_name(s) for s in valid],
        status="resolved",
        adopted_source=_source_type_name(top),
        reason=(
            f"可靠性({top_rel})"
            f"與置信度({top.get('confidence', 1.0)})最高"
        ),
        confidence="high" if top_rel >= 4 else "medium",
        keep_both_versions=False,
    )
