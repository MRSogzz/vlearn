from pathlib import Path
import sys

# 嘗試多個 WSL 路徑（Windows 11 / Windows 10 路徑不同）
candidates = [
    Path(r"\\wsl.localhost\Ubuntu\home\ming\projects\qwen38-27b-flash-mtp\llmserver.sh"),
    Path(r"\\wsl$\Ubuntu\home\ming\projects\qwen38-27b-flash-mtp\llmserver.sh"),
]

target = None
for p in candidates:
    if p.parent.exists():
        target = p
        break

if target is None:
    print("ERROR: 無法訪問 WSL 路徑，請檢查發行版名稱和用戶名")
    print("嘗試過的路徑:")
    for p in candidates:
        print(f"  {p}")
    sys.exit(1)

print(f"target: {target}")

# 備份
backup = target.with_suffix(".sh.bak_reasoning_fix")
if target.exists():
    backup.write_bytes(target.read_bytes())
    print(f"backup: {backup}")

content = r'''#!/usr/bin/env bash
# ===========================================================================
#  llama.cpp-qwen38-flash runtime launcher (Linux)
#  The Windows equivalent is llmserver.bat -- same parameters, same order.
#
#  Engine binary: build/src/bin (your own build) is preferred, build/bin is the
#  fallback. There is no prebuilt Linux binary, so in practice you build it.
#
#  All of OUR switches live in features.ini, which the engine reads itself
#  through --features-file. Only upstream-known parameters are set here.
#
#  NOTE: features.ini holds "spec-draft-vocab-map = maps/..." -- a path relative
#  to the working directory. That is why this script cds to its own folder.
# ===========================================================================
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

SERVER=""
if [ -x build/src/bin/llama-server ]; then
  SERVER=build/src/bin
elif [ -x build/bin/llama-server ]; then
  SERVER=build/bin
else
  cat >&2 <<'EOF'
[error] llama-server not found. There is no prebuilt Linux binary -- build it:

  git clone https://github.com/zgsndzq/llama.cpp-qwen38-flash code
  cmake -B build/src -S code -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_CUDA_ARCHITECTURES=89 \
    -DGGML_CUDA=ON -DGGML_CUDA_FA=ON \
    -DGGML_CUDA_FA_QUANTS=all \
    -DLLAMA_CURL=OFF
  cmake --build build/src -j --target llama-server llama-bench llama-quantize

  CUDA_ARCH: 89 = Ada (4060/4070/4090), 86 = Ampere (3060/3080). Do not let
  CMake guess it -- a wrong arch builds fine and then fails to run.
  GGML_CUDA_FA_QUANTS=all matters: the default list omits the quantised-KV
  combos this model uses, and the runner then silently converts K/V to f16.
EOF
  exit 1
fi

# shared libraries: the built tree keeps them next to the binary
export LD_LIBRARY_PATH="$PWD/$SERVER:$PWD/build/bin:${LD_LIBRARY_PATH:-}"

MODEL="Qwen3.8-27B-Flash-MTP.gguf"
# context size; drop to 32768 on a 6 GB card (and kv-vram-cells in features.ini too)
CTX=65536
# KV precision. cells kept in VRAM = features.ini kv-vram-cells (must be <= CTX).
CTK=q4_0
CTV=q4_0
# thinking block token cap.
# CHANGED: 0 = no thinking token at all (fixes '/' repetition bug in
# Hermes/Pi + vision requests). Original value was 16384 (hard cap = thinking
# always generated, which leaks into the content field and causes degenerate
# output like '////...' when the client doesn't support reasoning separation).
REBUDGET=0
# draft width ceiling, the adaptive controller stays at or below it.
DRAFT_N=4
# ngram lookup drafter
NMATCH=24
NGMIN=24
NGMAX=64
LOOKUP_N=$NGMAX

# a stale instance holds the port and its VRAM, so drop it before binding again
pkill -f llama-server >/dev/null 2>&1 || true
sleep 2

args=(
  -m "$PWD/weights/$MODEL"
  --host 127.0.0.1 --port 18080 --parallel 1 -rea off --no-ui
  -c "$CTX" -b 4096 -t 8 -ngl 99 -fa on -ctk "$CTK" -ctv "$CTV"
  --reasoning-budget "$REBUDGET"
  --reasoning-budget-message "思考預算即將耗盡，請基於現有分析直接給出最終答案。"
  # CHANGED: reasoning_effort "medium" -> "none"
  # "medium" still forces the model to generate reasoning trace even when
  # --reasoning-budget is 0 (the model starts thinking, budget clamps at 0,
  # but the leading "耗盡..." + " response" prefix still appears).
  # "none" fully disables reasoning for this chat template.
  --chat-template-kwargs '{"reasoning_effort": "none"}'
  --jinja
  --spec-type ngram-mod,draft-mtp-adaptive --spec-draft-n-max "$DRAFT_N"
  --spec-lookup-n-max "$LOOKUP_N" --spec-ngram-mod-n-min "$NGMIN"
  --spec-ngram-mod-n-max "$NGMAX"
  --spec-ngram-mod-n-match "$NMATCH"
  --features-file features.ini
  --alias "Qwen3.8-27B-Flash-MTP"
)

# vision projector. VISION=1 mounts it, but only when the file is actually there.
VISION=1
MMPROJ="$PWD/weights/mmproj-Qwen3.8-27B-Q8_0.gguf"
if [ "$VISION" = "1" ]; then
  if [ -f "$MMPROJ" ]; then
    args+=(--mmproj "$MMPROJ" --image-min-tokens 1024)
  else
    echo "[warn] $MMPROJ not found - starting without vision" >&2
  fi
fi

exec "$SERVER/llama-server" "${args[@]}"
'''

target.write_text(content, encoding="utf-8")
print(f"written: {target}")
print()
print("關鍵改動：")
print("  1. REBUDGET=16384 -> REBUDGET=0")
print("  2. reasoning_effort: medium -> none")
print()
print("驗證改動：")
text = target.read_text(encoding="utf-8")
for line in text.splitlines():
    if "REBUDGET=" in line and not line.strip().startswith("#"):
        print(f"  {line.strip()}")
    if "reasoning_effort" in line and not line.strip().startswith("#"):
        print(f"  {line.strip()}")

