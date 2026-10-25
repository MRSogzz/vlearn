import yaml
import shutil
from pathlib import Path

cfg_path = Path(r"C:\Users\User\AppData\Local\hermes\config.yaml")
bak_path = cfg_path.with_suffix(".yaml.bak")
shutil.copy2(cfg_path, bak_path)
print(f"backup: {bak_path}")

data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))

# 修改 model 段
model = data.setdefault("model", {})
model["reasoning_control"] = True
model["reasoning_format"] = "auto"
print(f"model.reasoning_control = True")
print(f"model.reasoning_format = auto")

# 同步到 custom_providers（如果有 18080 的條目）
for cp in data.get("custom_providers", []):
    if "18080" in cp.get("base_url", ""):
        cp["reasoning_control"] = True
        cp["reasoning_format"] = "auto"
        print(f"custom_provider[{cp.get('name', '?')}]: +reasoning fields")

# 同步到 providers.custom（如果有）
if "custom" in data.get("providers", {}):
    pc = data["providers"]["custom"]
    if "18080" in pc.get("base_url", ""):
        pc["reasoning_control"] = True
        pc["reasoning_format"] = "auto"
        print(f"providers.custom: +reasoning fields")

cfg_path.write_text(
    yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
    encoding="utf-8",
)
print(f"\nwritten: {cfg_path}")

