"""冷請求重複循環檢測腳本。

用法：python test_cold_repetition.py

每次運行生成不同的 prompt（時間戳 + 隨機數作種子），
對同一段輸入發兩種配置的請求：
  A) 標準 OpenAI 格式（無 reasoning 字段）
  B) 帶 reasoning_control + backend_sampling=False

對比兩種配置下模型是否進入重複循環。

重複循環判定標準：
  - 出現連續 50+ 個相同字符
  - 出現同一短語重複 3+ 次
  - finish_reason == "length"（說明撞到 max_tokens）
  - 輸出裡 "/" 或 "=" 佔比 > 30%
"""
from __future__ import annotations

import json
import random
import re
import string
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx


# ══════════════════════════════════════════════════════════════════
#  隨機 prompt 生成
# ══════════════════════════════════════════════════════════════════

TOPICS = [
    "Python 異步編程的最佳實踐",
    "中世紀歐洲城堡的建築演變",
    "咖啡烘焙曲線對風味的影響",
    "量子糾纏與貝爾不等式",
    "爵士樂的和聲理論演進",
    "城市道路規劃與行人流量",
    "機器學習模型的可解釋性",
    "木工榫卯結構的力學分析",
    "天文觀測中的光害問題",
    "葡萄酒釀造中的發酵控制",
    "編譯器優化的歷史發展",
    "颱風路徑預報的物理模型",
]

NAMES = [
    "張三", "李四", "王五", "林六", "陳七",
    "Alice", "Bob", "Carol", "Dave", "Eve",
    "Dr. Smith", "Prof. Johnson", "Dr. Lee", "Ms. Chen",
]

NUMBERS = [
    3.14, 2.718, 42, 137, 1024, 2048, 0.618, 99.9,
    365, 86400, 1000000, 7.5, 1234, 5678, 90.0,
]


def _random_word() -> str:
    length = random.randint(3, 10)
    return "".join(random.choices(string.ascii_lowercase, k=length))


def _random_sentence() -> str:
    topic = random.choice(TOPICS)
    name = random.choice(NAMES)
    num = random.choice(NUMBERS)
    templates = [
        f"關於{topic}，{name}認為關鍵在於{num}這個數值。",
        f"{name}指出，{topic}的核心問題是效率與穩定的平衡。",
        f"在討論{topic}時，我們發現{num}是一個重要參考值。",
        f"研究{topic}的過程中，{name}發現了{_random_word()}現象。",
        f"根據{name}的實驗，當數值達到{num}時，{topic}會出現質變。",
        f"針對{topic}，建議從{_random_word()}與{_random_word()}兩個角度分析。",
        f"{name}在{num}次實驗後，得出關於{topic}的結論。",
        f"關於{topic}的第三個要點，是{_random_word()}與{_random_word()}的交互作用。",
    ]
    return random.choice(templates)


def _random_paragraph(n_sentences: int) -> str:
    return " ".join(_random_sentence() for _ in range(n_sentences))


def _random_list_block(n_items: int) -> str:
    lines = []
    for i in range(1, n_items + 1):
        word = _random_word()
        num = random.choice(NUMBERS)
        lines.append(f"{i}. {word}（權重 {num}）—— {_random_sentence()}")
    return "\n".join(lines)


def _random_table_block(rows: int, cols: int) -> str:
    lines = ["| " + " | ".join(_random_word() for _ in range(cols)) + " |"]
    lines.append("|" + "|".join(["---"] * cols) + "|")
    for _ in range(rows):
        lines.append("| " + " | ".join(
            f"{random.choice(NUMBERS)}" for _ in range(cols)
        ) + " |")
    return "\n".join(lines)


def _random_qa_block() -> str:
    q = f"問題：{_random_sentence()}"
    a = f"回答：{_random_sentence()}{_random_sentence()}"
    return f"{q}\n{a}"


def generate_random_prompt(
    target_chars: int = 15000,
    seed: Optional[int] = None,
) -> tuple[str, int, str]:
    """生成目標長度的隨機 prompt。

    Returns:
        (prompt_text, seed_used, signature)
        signature 用於識別本次測試。
    """
    if seed is None:
        seed = int(time.time() * 1000) + random.randint(0, 999999)
    random.seed(seed)

    signature = f"{seed}-{int(time.time())}"

    parts: list[str] = []
    parts.append(f"【測試會話 #{signature}】")
    parts.append("")

    # 交替使用不同結構，模擬真實長文檔
    structures = [
        ("paragraph", 5),
        ("list", 8),
        ("paragraph", 4),
        ("table", 6),
        ("qa", 3),
        ("paragraph", 6),
        ("list", 10),
        ("table", 8),
    ]

    total = len(parts[0])
    idx = 0
    while total < target_chars:
        kind, size = structures[idx % len(structures)]
        idx += 1

        if kind == "paragraph":
            block = f"## 段落 {idx}\n{_random_paragraph(size)}"
        elif kind == "list":
            block = f"## 清單 {idx}\n{_random_list_block(size)}"
        elif kind == "table":
            block = f"## 表格 {idx}\n{_random_table_block(size, 4)}"
        else:  # qa
            block = f"## 問答 {idx}\n" + "\n\n".join(
                _random_qa_block() for _ in range(size)
            )

        parts.append(block)
        parts.append("")
        total += len(block)

    # 結尾給出一個開放問題（避免模型簡單 copy）
    ending = (
        f"以上是關於「{random.choice(TOPICS)}」的資料。"
        "請用三句話總結核心要點，並指出資料中可能存在的矛盾之處。"
    )
    parts.append(ending)

    prompt = "\n".join(parts)
    return prompt, seed, signature


# ══════════════════════════════════════════════════════════════════
#  Token 估算
# ══════════════════════════════════════════════════════════════════

def estimate_tokens(text: str) -> int:
    """粗略估算 token 數。

    Qwen 類模型：
      - CJK 字符約 1 token
      - 英文約 0.3 token / char（4 chars / token）
      - 數字 / 符號約 0.5 token
    保守取 1.3 chars/token（混合文本）。
    """
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    non_cjk = len(text) - cjk
    # CJK 1:1，英文/符號約 4:1
    return cjk + max(1, non_cjk // 4)


# ══════════════════════════════════════════════════════════════════
#  循環檢測
# ══════════════════════════════════════════════════════════════════

REPEAT_CHAR_RE = re.compile(r"(.)\1{49,}")  # 連續 50+ 相同字符


def _longest_repeat_run(text: str) -> tuple[str, int]:
    """找最長連續相同字符。"""
    best_char = ""
    best_len = 0
    cur_char = ""
    cur_len = 0
    for c in text:
        if c == cur_char:
            cur_len += 1
        else:
            if cur_len > best_len:
                best_len = cur_len
                best_char = cur_char
            cur_char = c
            cur_len = 1
    if cur_len > best_len:
        best_len = cur_len
        best_char = cur_char
    return best_char, best_len


def _repeated_phrases(text: str, min_len: int = 10, top: int = 5) -> list[tuple[str, int]]:
    """找重複出現的短語（相鄰 token 連續重複）。"""
    # 用 n-gram 近似
    n = min_len
    counts: Counter = Counter()
    for i in range(len(text) - n):
        counts[text[i:i + n]] += 1
    # 只保留出現 >= 3 次的
    candidates = [(s, c) for s, c in counts.items() if c >= 3]
    # 去除被其他更長串包含的
    candidates.sort(key=lambda x: (-x[1], -len(x[0])))
    return candidates[:top]


def detect_repetition(text: str) -> dict:
    """綜合判定是否進入重複循環。"""
    result = {
        "length": len(text),
        "looks_looped": False,
        "reasons": [],
        "char_ratio": {},
        "longest_run": ("", 0),
        "top_repeats": [],
    }

    if not text:
        result["reasons"].append("empty")
        return result

    # 字符比例
    char_counts = Counter(text)
    for ch in ["/", "=", "-", " ", "\n"]:
        ratio = char_counts.get(ch, 0) / len(text)
        if ratio > 0:
            result["char_ratio"][repr(ch)] = round(ratio, 3)

    # 最長連續相同字符
    best_ch, best_len = _longest_repeat_run(text)
    result["longest_run"] = (best_ch, best_len)
    if best_len >= 50:
        result["looks_looped"] = True
        result["reasons"].append(f"longest_run={best_len}x{repr(best_ch)}")

    # 重複短語
    reps = _repeated_phrases(text, min_len=15, top=5)
    result["top_repeats"] = reps
    if reps and reps[0][1] >= 5:
        result["looks_looped"] = True
        result["reasons"].append(f"phrase_repeat={reps[0][1]}x")

    # 特殊字符佔比
    special = sum(char_counts.get(c, 0) for c in "/=-_")
    if special / len(text) > 0.30:
        result["looks_looped"] = True
        result["reasons"].append(f"special_chars={special/len(text):.0%}")

    return result


# ══════════════════════════════════════════════════════════════════
#  HTTP 請求
# ══════════════════════════════════════════════════════════════════

def send_cold_request(
    base_url: str,
    model: str,
    api_key: str,
    prompt: str,
    max_tokens: int,
    mode: str,  # "standard" | "reasoning_aware"
) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "stream": True,
    }
    if mode == "reasoning_aware":
        payload["reasoning_control"] = True
        payload["reasoning_format"] = "auto"
        payload["backend_sampling"] = False
        payload["return_progress"] = True
        payload["timings_per_token"] = True
        payload["sse_ping_interval"] = 1

    chunks: list[str] = []
    finish_reason = None
    content_tokens = 0
    reasoning_tokens = 0

    with httpx.stream(
        "POST",
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
        json=payload,
        timeout=600,
    ) as r:
        if r.status_code != 200:
            return {
                "mode": mode,
                "error": f"HTTP {r.status_code}",
                "body": r.read().decode()[:500],
            }
        for line in r.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            data_str = line[6:].strip()
            if data_str == "[DONE]":
                break
            try:
                obj = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            choices = obj.get("choices", [])
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get("delta", {})
            c = delta.get("content")
            if c:
                chunks.append(c)
                content_tokens += 1
            # 兼容 reasoning 字段
            rc = delta.get("reasoning_content") or delta.get("reasoning")
            if rc:
                reasoning_tokens += 1
            fr = choice.get("finish_reason")
            if fr:
                finish_reason = fr

    text = "".join(chunks)
    return {
        "mode": mode,
        "text": text,
        "finish_reason": finish_reason,
        "chunks": content_tokens,
        "reasoning_chunks": reasoning_tokens,
    }


# ══════════════════════════════════════════════════════════════════
#  主流程
# ══════════════════════════════════════════════════════════════════

def run_one_case(
    base_url: str, model: str, api_key: str,
    target_chars: int, max_tokens: int,
    seed: Optional[int] = None,
) -> dict:
    prompt, seed_used, signature = generate_random_prompt(
        target_chars=target_chars, seed=seed
    )
    approx_tokens = estimate_tokens(prompt)

    print(f"\n{'='*70}")
    print(f"[CASE {signature}] seed={seed_used}")
    print(f"  prompt chars  : {len(prompt):,}")
    print(f"  approx tokens : ~{approx_tokens:,}")
    print(f"  max_tokens    : {max_tokens}")
    print(f"  prompt head   : {prompt[:120]}...")
    print(f"{'='*70}")

    results = {}
    for mode in ["standard", "reasoning_aware"]:
        print(f"\n  → sending [{mode}] ... ", end="", flush=True)
        t0 = time.time()
        res = send_cold_request(
            base_url, model, api_key, prompt, max_tokens, mode
        )
        elapsed = time.time() - t0

        if "error" in res:
            print(f"ERROR ({elapsed:.1f}s) {res['error']}")
            results[mode] = res
            continue

        text = res["text"]
        diag = detect_repetition(text)
        print(f"done in {elapsed:.1f}s, "
              f"output {len(text):,} chars, "
              f"finish={res['finish_reason']}")

        print(f"     longest_run: {diag['longest_run'][1]}x {repr(diag['longest_run'][0])}")
        print(f"     char_ratio : {diag['char_ratio']}")
        if diag["top_repeats"]:
            print(f"     top repeats: {diag['top_repeats'][:3]}")
        if diag["looks_looped"]:
            print(f"     ⚠️  LOOPED: {diag['reasons']}")
        else:
            print(f"     ✅ normal")

        results[mode] = {
            "elapsed": elapsed,
            "finish_reason": res["finish_reason"],
            "output_len": len(text),
            "chunks": res["chunks"],
            "reasoning_chunks": res["reasoning_chunks"],
            "diagnostics": diag,
            "preview": text[:300],
        }

    return {
        "signature": signature,
        "seed": seed_used,
        "prompt_chars": len(prompt),
        "approx_tokens": approx_tokens,
        "results": results,
    }


def main():
    base_url = "http://127.0.0.1:18080/v1"
    model = "Qwen3.8-27B-Flash-MTP"
    api_key = "sk-local"

    # 3 個不同種子
    seeds = [
        int(time.time()),
        int(time.time()) + 7777,
        int(time.time()) + 14142,
    ]

    all_results = []
    for i, seed in enumerate(seeds, 1):
        print(f"\n\n{'#'*70}")
        print(f"#  TEST {i}/3  ")
        print(f"{'#'*70}")
        r = run_one_case(
            base_url, model, api_key,
            target_chars=15000,
            max_tokens=400,
            seed=seed,
        )
        all_results.append(r)

    # ─── 彙總 ──────────────────────────────────────────────
    print(f"\n\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"{'test':<8} {'mode':<20} {'finish':<10} {'out':<8} {'looped':<8}")
    print(f"{'-'*8} {'-'*20} {'-'*10} {'-'*8} {'-'*8}")

    for i, r in enumerate(all_results, 1):
        for mode in ["standard", "reasoning_aware"]:
            res = r["results"].get(mode, {})
            if "error" in res:
                print(f"{i:<8} {mode:<20} {'ERROR':<10} {'':<8} {res['error'][:20]}")
                continue
            diag = res.get("diagnostics", {})
            looped = "YES ⚠️" if diag.get("looks_looped") else "no"
            print(f"{i:<8} {mode:<20} "
                  f"{res.get('finish_reason','?'):<10} "
                  f"{res.get('output_len', 0):<8} "
                  f"{looped:<8}")

    # 保存結果
    out_path = Path("test_repetition_results.json")
    out_path.write_text(
        json.dumps(all_results, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\ndetailed results saved to: {out_path}")

    # 返回碼
    any_looped = any(
        r["results"].get(mode, {}).get("diagnostics", {}).get("looks_looped")
        for r in all_results
        for mode in ["standard", "reasoning_aware"]
    )
    sys.exit(1 if any_looped else 0)


if __name__ == "__main__":
    main()

