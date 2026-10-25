import glob
from app.context import AppContext
from app.keyframes.describe import describe_frame

ctx = AppContext.from_config("config/default.yaml")
frames = sorted(glob.glob("cache/frames/8S0FDjFBj8o/*_720p.jpg"))
if not frames:
    print("no frames — run analyze first")
    raise SystemExit(1)

frame = frames[0]
print("using frame:", frame)

result = describe_frame(
    ctx, "diag_qwen", frame,
    timestamp=113.0,
    time_range=(110.0, 116.0),
    frame_ref="kf_diag",
)
if not result:
    print("FAIL: describe_frame returned None")
else:
    print("summary:", result.get("summary"))
    print(f"assertions: {len(result.get('assertions', []))}")
    for a in result.get("assertions", [])[:8]:
        print(f"  [{a.get('kind')}] {a.get('claim')}")
