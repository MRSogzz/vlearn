from app.keyframes.selector import (
    select_keyframes_seek, select_keyframes_dispatch,
)


def test_seek_margin_boundary():
    """margin 邊界：右邊界 = t_{i+1} - 0.4"""
    out = select_keyframes_seek(
        [1.0, 2.0], duration=10,
        max_window_sec=8.0, min_gap_sec=1.0,
        right_margin_sec=0.4,
    )
    first = out[0]
    assert abs(first.window_end - (2.0 - 0.4)) < 1e-6
    assert first.chosen_ts < 2.0


def test_seek_last_point_bounded():
    """最後一個變化點：右邊界 = min(t + max_window, duration)"""
    out = select_keyframes_seek(
        [9.5], duration=10,
        max_window_sec=8.0, min_gap_sec=1.0,
    )
    assert out[0].window_end <= 10.0


def test_seek_trigger_type():
    """trigger_type 標記為 seek_margin"""
    out = select_keyframes_seek([1.0, 2.0], duration=10)
    for f in out:
        assert f.trigger_type == "seek_margin"


def test_seek_one_to_two_candidates():
    """窗口內只有 1-2 個候選時間點時，chosen 落在窗口內"""
    out = select_keyframes_seek(
        [1.0, 1.5], duration=10,
        max_window_sec=8.0, min_gap_sec=0.6,
        right_margin_sec=0.2,
        left_candidates=3,
    )
    for f in out:
        assert f.window_start <= f.chosen_ts <= f.window_end


def test_seek_long_window_front_third():
    """窗口 > 30s 時，只在窗口前 1/3 取樣"""
    out = select_keyframes_seek(
        [10.0, 100.0], duration=200,
        min_gap_sec=1.0,
        right_margin_sec=0.4,
        long_window_sec=30.0,
    )
    first = out[0]
    # 前 1/3 邊界 = 10 + (100-10-0.4)/3 ≈ 39.87
    assert first.chosen_ts <= 40.0


def test_dispatch_frame_exact():
    """dispatcher mode=frame_exact 走原 select_keyframes"""
    out = select_keyframes_dispatch(
        [1.0, 2.0], duration=10, mode="frame_exact", fps=30.0,
    )
    assert out[0].trigger_type == "scene_change"


def test_dispatch_seek():
    """dispatcher mode=seek 走 select_keyframes_seek"""
    out = select_keyframes_dispatch(
        [1.0, 2.0], duration=10, mode="seek",
    )
    assert out[0].trigger_type == "seek_margin"
