"""驗證 arbitrate 在真衝突場景下的行為。

覆蓋：
- 兩個高可靠來源（official_subtitle + platform_metadata）不一致 → unresolved + keep_both
- 單強源壓過弱源 → resolved
- keyframe_ocr(4) vs keyframe_vlm(3) → 優先 ocr
- keyframe_vlm(3) vs asr(2) → 優先 vlm
- 全帶 quality_flags → 退回全集
- 空 summaries → unresolved
"""
from app.evidence.arbiter import arbitrate, RELIABILITY
from app.schemas import EvidenceBundle, SourceType


def _bundle(bid: str = "b1") -> EvidenceBundle:
    return EvidenceBundle(
        id=bid, video_id="test_video",
        time_range=(0.0, 10.0),
        summary_ids=[],
        status="conflict",
    )


def _s(source_type: SourceType, confidence: float = 1.0,
       quality_flags: list | None = None, claim: str = "") -> dict:
    return {
        "source_type": source_type,
        "confidence": confidence,
        "quality_flags": quality_flags or [],
        "claim": claim,
    }


# ---------- 真衝突：兩個強源不一致 ----------

def test_two_strong_sources_unresolved():
    """official_subtitle(5) vs platform_metadata(5) → unresolved + keep_both。"""
    r = arbitrate(_bundle(), [
        _s(SourceType.OFFICIAL_SUBTITLE, claim="red"),
        _s(SourceType.PLATFORM_METADATA, claim="blue"),
    ])
    assert r.status == "unresolved"
    assert r.keep_both_versions is True
    assert r.adopted_source is None


def test_ocr_vs_subtitle_high_confidence_unresolved():
    """official_subtitle(5) vs keyframe_ocr(4) → 差距 20% 內，unresolved。"""
    r = arbitrate(_bundle(), [
        _s(SourceType.OFFICIAL_SUBTITLE, claim="2.5%"),
        _s(SourceType.KEYFRAME_OCR, claim="3.5%"),
    ])
    # weight: 5*1.0 = 5 vs 4*1.0 = 4; 4 / 5 = 0.8 → 恰在 80% 閾值上
    assert r.status == "unresolved"
    assert r.keep_both_versions is True


# ---------- 強源壓過弱源：resolved ----------

def test_subtitle_beats_danmaku():
    """official_subtitle(5) vs danmaku(1) → resolved + adopted=subtitle。"""
    r = arbitrate(_bundle(), [
        _s(SourceType.OFFICIAL_SUBTITLE, claim="250,000 people"),
        _s(SourceType.DANMAKU, claim="2500 people"),
    ])
    assert r.status == "resolved"
    assert r.adopted_source == "official_subtitle"
    assert r.keep_both_versions is False
    assert r.confidence == "high"


def test_ocr_beats_vlm():
    """keyframe_ocr(4) vs keyframe_vlm(3) → resolved + adopted=ocr。"""
    r = arbitrate(_bundle(), [
        _s(SourceType.KEYFRAME_OCR, claim="標題: Numbers"),
        _s(SourceType.KEYFRAME_VLM, claim="標題: Number"),
    ])
    assert r.status == "resolved"
    assert r.adopted_source == "keyframe_ocr"
    assert r.confidence == "high"  # reliability >= 4


def test_vlm_beats_asr():
    """keyframe_vlm(3) vs asr(2) → resolved + adopted=vlm。"""
    r = arbitrate(_bundle(), [
        _s(SourceType.KEYFRAME_VLM, claim="70.5 percent"),
        _s(SourceType.ASR, claim="70.5, 這樣..."),  # ASR 斷句錯誤
    ])
    assert r.status == "resolved"
    assert r.adopted_source == "keyframe_vlm"
    # reliability=3 < 4 → confidence=medium
    assert r.confidence == "medium"


# ---------- 質量降權 ----------

def test_quality_flags_excluded_when_other_valid():
    """official_subtitle 帶 quality_flags，platform_metadata 乾淨 → 選 platform_metadata。"""
    r = arbitrate(_bundle(), [
        _s(SourceType.OFFICIAL_SUBTITLE, claim="x", quality_flags=["low_asr_conf"]),
        _s(SourceType.PLATFORM_METADATA, claim="y"),
    ])
    # 過濾掉帶 flags 的 → 只剩 platform_metadata
    assert r.status == "resolved"
    assert r.adopted_source == "platform_metadata"


def test_all_quality_flags_fallback_to_full_set():
    """全部帶 quality_flags → 退回全集仲裁，不返回空結果。"""
    r = arbitrate(_bundle(), [
        _s(SourceType.OFFICIAL_SUBTITLE, claim="x", quality_flags=["blurry"]),
        _s(SourceType.DANMAKU, claim="y", quality_flags=["blurry"]),
    ])
    # 退回全集後：subtitle(5) vs danmaku(1) → resolved
    assert r.status == "resolved"
    assert r.adopted_source == "official_subtitle"


# ---------- 空輸入 ----------

def test_empty_summaries_unresolved():
    r = arbitrate(_bundle(), [])
    assert r.status == "unresolved"
    assert r.sources == []
    assert r.confidence == "low"
    assert r.reason == "無可用證據"


# ---------- 兼容舊 alias ----------

def test_keyframe_deprecated_alias():
    """SourceType.KEYFRAME（舊 alias）應與 keyframe_vlm 同可靠性。"""
    assert RELIABILITY[SourceType.KEYFRAME] == RELIABILITY[SourceType.KEYFRAME_VLM]


# ---------- 置信度差異 ----------

def test_high_confidence_dominates():
    """兩個同源，一個 confidence=1.0，一個 0.3 → resolved。"""
    r = arbitrate(_bundle(), [
        _s(SourceType.OFFICIAL_SUBTITLE, confidence=1.0, claim="x"),
        _s(SourceType.OFFICIAL_SUBTITLE, confidence=0.3, claim="y"),
    ])
    # weight: 5.0 vs 1.5, 1.5/5.0 = 0.3 < 0.8 → resolved
    assert r.status == "resolved"
    assert r.adopted_source == "official_subtitle"
