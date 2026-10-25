from app.keyframes.selector import select_keyframes, _frame_before

FPS = 30.0
MAX_W = 8.0
MIN_GAP = 1.0


def test_right_boundary_truncation():
    """1s 與 2s 變化點：1s 的選幀不得落在 >= 2s。"""
    scores = {1.0: 0.2, 1.5: 0.9, 2.0: 1.0, 2.5: 0.95}
    out = select_keyframes([1.0, 2.0], duration=10, fps=FPS,
                           max_window_sec=MAX_W, min_gap_sec=MIN_GAP,
                           frame_scores=scores)
    first = out[0]
    assert first.window_end <= 2.0
    assert first.chosen_ts < 2.0            # 不得搶 2s 的幀
    assert first.chosen_ts == 1.5           # 窗口內最清晰


def test_dense_points_merged():
    out = select_keyframes([1.0, 1.3, 1.6, 5.0], duration=10, fps=FPS,
                           max_window_sec=MAX_W, min_gap_sec=MIN_GAP)
    assert len(out) == 2                    # 1.x 合併為一次，5.0 保留


def test_last_point_bounded_by_duration():
    out = select_keyframes([9.5], duration=10, fps=FPS,
                           max_window_sec=MAX_W, min_gap_sec=MIN_GAP)
    assert out[0].window_end <= 10.0


def test_frame_before_strictly_smaller():
    assert _frame_before(2.0, FPS) < 2.0
    # 嚴格小於 2.0 的最後一幀：距 2.0 至多一幀（允許正好等於一幀邊界）
    assert _frame_before(2.0, FPS) >= 2.0 - 1.0 / FPS - 1e-9
    # fps=30、ts=2.0（恰在幀邊界）應精確等於第 59 幀
    assert abs(_frame_before(2.0, FPS) - 59 / FPS) < 1e-9
