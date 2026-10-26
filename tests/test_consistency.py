"""驗證 check_bundle 的一致性判定。

覆蓋：
- 顏色衝突（不同核心色） vs 顏色一致（同核心不同表述）
- 方向衝突 vs 方向一致
- 數字差異 > 20% → suspect
- 單源 / 空 bundle 的兜底
"""
from app.evidence.consistency import _normalize_color, _normalize_number, check_bundle


def _make_summary(sid: str, source_type: str, assertions: list[dict]) -> dict:
    return {
        "id": sid,
        "video_id": "test_video",
        "time_range": (0.0, 10.0),
        "source_type": source_type,
        "summary": "",
        "assertions": assertions,
    }


def _make_bundle(bid: str, summary_ids: list[str]) -> dict:
    return {
        "id": bid,
        "video_id": "test_video",
        "time_range": (0.0, 10.0),
        "summary_ids": summary_ids,
        "status": "pending",
    }


# ---------- 顏色衝突 ----------

def test_color_conflict_different_cores():
    """字幕說 red，圖片說 blue → conflict。"""
    summaries = {
        "s1": _make_summary("s1", "official_subtitle",
                            [{"claim": "red curtain", "kind": "color", "ref": "sub_1"}]),
        "s2": _make_summary("s2", "keyframe_vlm",
                            [{"claim": "blue curve", "kind": "color", "ref": "kf_1"}]),
    }
    bundle = _make_bundle("b1", ["s1", "s2"])
    assert check_bundle(bundle, summaries) == "conflict"


def test_color_consistent_same_core():
    """字幕說 red curtain，圖片說 深紅色帷幕 → 同一核心色 red，consistent。"""
    summaries = {
        "s1": _make_summary("s1", "official_subtitle",
                            [{"claim": "red curtain", "kind": "color", "ref": "sub_1"}]),
        "s2": _make_summary("s2", "keyframe_vlm",
                            [{"claim": "深紅色帷幕", "kind": "color", "ref": "kf_1"}]),
    }
    bundle = _make_bundle("b1", ["s1", "s2"])
    assert check_bundle(bundle, summaries) == "consistent"


def test_color_three_aliases_same_core():
    """red / 紅 / 深紅 → 全部歸一化為 red，consistent。"""
    summaries = {
        "s1": _make_summary("s1", "official_subtitle",
                            [{"claim": "red", "kind": "color", "ref": "r1"}]),
        "s2": _make_summary("s2", "keyframe_vlm",
                            [{"claim": "紅色帷幕", "kind": "color", "ref": "r2"}]),
        "s3": _make_summary("s3", "keyframe_vlm",
                            [{"claim": "深紅", "kind": "color", "ref": "r3"}]),
    }
    bundle = _make_bundle("b1", ["s1", "s2", "s3"])
    assert check_bundle(bundle, summaries) == "consistent"


# ---------- 方向衝突 ----------

def test_direction_conflict():
    """字幕說 right，圖片說 left → conflict。"""
    summaries = {
        "s1": _make_summary("s1", "official_subtitle",
                            [{"claim": "right hand", "kind": "direction", "ref": "sub_1"}]),
        "s2": _make_summary("s2", "keyframe_vlm",
                            [{"claim": "面向左側", "kind": "direction", "ref": "kf_1"}]),
    }
    bundle = _make_bundle("b1", ["s1", "s2"])
    assert check_bundle(bundle, summaries) == "conflict"


def test_direction_consistent():
    """兩個源都描述向右 → consistent。"""
    summaries = {
        "s1": _make_summary("s1", "official_subtitle",
                            [{"claim": "right side", "kind": "direction", "ref": "s1"}]),
        "s2": _make_summary("s2", "keyframe_vlm",
                            [{"claim": "right side", "kind": "direction", "ref": "s2"}]),
    }
    bundle = _make_bundle("b1", ["s1", "s2"])
    assert check_bundle(bundle, summaries) == "consistent"


# ---------- 數字差異 ----------

def test_number_suspect_big_difference():
    """250,000 vs 25,000 → 差 10 倍 → suspect。"""
    summaries = {
        "s1": _make_summary("s1", "official_subtitle",
                            [{"claim": "250,000 people", "kind": "number", "ref": "s1"}]),
        "s2": _make_summary("s2", "keyframe_vlm",
                            [{"claim": "25,000 people", "kind": "number", "ref": "s2"}]),
    }
    bundle = _make_bundle("b1", ["s1", "s2"])
    assert check_bundle(bundle, summaries) == "suspect"


def test_number_consistent_same_value():
    """70.5 percent vs 70.5% → 數值相同 → consistent。"""
    summaries = {
        "s1": _make_summary("s1", "official_subtitle",
                            [{"claim": "70.5 percent", "kind": "number", "ref": "s1"}]),
        "s2": _make_summary("s2", "keyframe_vlm",
                            [{"claim": "70.5%", "kind": "number", "ref": "s2"}]),
    }
    bundle = _make_bundle("b1", ["s1", "s2"])
    assert check_bundle(bundle, summaries) == "consistent"


def test_number_close_within_20_percent():
    """100 vs 110 → 差 10% < 20% → consistent。"""
    summaries = {
        "s1": _make_summary("s1", "official_subtitle",
                            [{"claim": "100 units", "kind": "number", "ref": "s1"}]),
        "s2": _make_summary("s2", "keyframe_vlm",
                            [{"claim": "110 units", "kind": "number", "ref": "s2"}]),
    }
    bundle = _make_bundle("b1", ["s1", "s2"])
    assert check_bundle(bundle, summaries) == "consistent"


def test_number_chinese_unit():
    """2.6 million vs 260萬 → 都歸一化為 2,600,000 → consistent。"""
    summaries = {
        "s1": _make_summary("s1", "official_subtitle",
                            [{"claim": "2.6 million", "kind": "number", "ref": "s1"}]),
        "s2": _make_summary("s2", "keyframe_vlm",
                            [{"claim": "260萬", "kind": "number", "ref": "s2"}]),
    }
    bundle = _make_bundle("b1", ["s1", "s2"])
    assert check_bundle(bundle, summaries) == "consistent"


# ---------- 兜底 ----------

def test_single_summary_consistent():
    """只有一個 summary → consistent（無多源可比）。"""
    summaries = {
        "s1": _make_summary("s1", "official_subtitle",
                            [{"claim": "red", "kind": "color", "ref": "s1"}]),
    }
    bundle = _make_bundle("b1", ["s1"])
    assert check_bundle(bundle, summaries) == "consistent"


def test_empty_summary_ids_consistent():
    """summary_ids 為空 → consistent。"""
    bundle = _make_bundle("b1", [])
    assert check_bundle(bundle, {}) == "consistent"


def test_missing_summary_ids_consistent():
    """summary_ids 指向不存在的 summary → 無成員 → consistent。"""
    bundle = _make_bundle("b1", ["nonexistent1", "nonexistent2"])
    assert check_bundle(bundle, {}) == "consistent"


# ---------- 輔助函數 ----------

def test_normalize_color_aliases():
    assert _normalize_color("red curtain") == "red"
    assert _normalize_color("深紅色帷幕") == "red"
    assert _normalize_color("RED") == "red"
    assert _normalize_color("藍色曲線") == "blue"
    assert _normalize_color("no color here") is None


def test_normalize_number_units():
    assert _normalize_number("70.5") == 70.5
    assert _normalize_number("70.5%") == 70.5
    assert _normalize_number("250,000 people") == 250000.0
    assert _normalize_number("2.6 million") == 2_600_000.0
    assert _normalize_number("260萬") == 2_600_000.0
    assert _normalize_number("no number") is None
