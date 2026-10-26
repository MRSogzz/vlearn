"""局部摘要。

兩條路徑：
  - LLM：ctx.router.available("local_summary") == True 時走模型
  - 正則：無 LLM 時抽取式 + 上下文感知斷言

斷言質量原則：
  - claim 是原文連續片段，不是孤立 token
  - 數字按值去重，跳過枚舉噪聲
  - 顏色/方向詞要求與鄰近實詞共現，且上下文不跨句
  - 英文方向詞排除 up/down/top/bottom（歧義）
  - 名稱只匹配成對引號
  - LLM 輸出後置過濾：枚舉數字/英文數詞/時間戳/抽象詞 + CJK 有效長度
"""
from __future__ import annotations

import json
import re

from app.context import AppContext
from app.summarize.prompts import SYSTEM_LOCAL_SUMMARY

# ---------- 數字 ----------
_NUM = re.compile(r"\d+(?:[.,]\d+)?%?")

# ---------- 顏色 / 方向 ----------
_COLORS = [
    "紅", "紅", "藍", "藍", "綠", "綠", "黑", "白", "黃", "黃", "紫", "橙", "灰", "粉",
    "red", "blue", "green", "black", "white", "yellow", "purple", "orange",
    "gray", "grey", "pink", "cyan", "brown",
]
_DIRECTIONS = [
    "左", "右", "前", "後", "後", "內", "內", "外",
    "left", "right", "north", "south", "east", "west",
]
_COLOR_RE = re.compile(r"(?<![A-Za-z])(" + "|".join(_COLORS) + r")(?![A-Za-z])", re.I)
_DIR_RE = re.compile(r"(?<![A-Za-z])(" + "|".join(_DIRECTIONS) + r")(?![A-Za-z])", re.I)

# ---------- 名稱（只匹配成對引號） ----------
_PAIRED_QUOTE = re.compile(
    r"[“”「」『』]([^“”「」『』]{2,30})[“”「」『』]"
    r'|"([^"\n]{2,30})"'
    r"|‘([^‘’]{2,30})’"
)

# ---------- 停用詞 / 單位 ----------
_STOPWORDS = {
    "a", "an", "the", "i", "he", "she", "it", "we", "you", "they",
    "them", "him", "her", "my", "your", "our", "their", "this", "that",
    "these", "those",
    "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "will", "would", "can", "could",
    "should", "may", "might", "do", "does", "did",
    "and", "or", "but", "if", "of", "to", "in", "on", "at",
    "by", "for", "with", "from", "as", "than", "so",
    "up", "down", "out", "off", "over", "under", "back",
    "forward", "backward", "here", "there", "now", "then",
    "just", "only", "also", "even", "still", "already",
    "very", "really", "quite", "too", "more", "most",
    "less", "least", "much", "many", "some", "any",
    "all", "both", "each", "every", "no", "not",
}
_UNITS = {
    "%", "$", "€", "¥", "£", "percent", "percentage",
    "million", "billion", "thousand", "hundred", "k", "m", "b",
    "元", "万", "萬", "亿", "億",
}

_SENTENCE_ENDS = "。！？\n"


def _is_cjk(s: str) -> bool:
    return any("\u4e00" <= c <= "\u9fff" for c in s)


def _is_sentence_end(text: str, i: int) -> bool:
    c = text[i]
    if c in _SENTENCE_ENDS:
        return True
    if c == ".":
        prev_digit = i > 0 and text[i - 1].isdigit()
        next_digit = i + 1 < len(text) and text[i + 1].isdigit()
        return not (prev_digit and next_digit)
    if c in "!?":
        return True
    return False


def _sentence_bounds(text: str, pos: int) -> tuple[int, int]:
    lo = 0
    for i in range(pos - 1, -1, -1):
        if _is_sentence_end(text, i):
            lo = i + 1
            break
    hi = len(text)
    for i in range(pos, len(text)):
        if _is_sentence_end(text, i):
            hi = i + 1
            break
    return lo, hi


def _context_number(text: str, start: int, end: int) -> str:
    lo, hi = _sentence_bounds(text, start)
    raw = text[start:end]

    if _is_cjk(text[lo:hi]):
        return text[lo:hi].strip()[:60]

    before = text[lo:start].split()[-1:]
    after = text[end:hi].split()[:1]

    parts: list[str] = []
    if before:
        tok = before[0].strip(".,;:!?，。；：！？")
        if tok and tok.lower() not in _STOPWORDS:
            parts.append(tok)
    parts.append(raw)
    if after:
        tok_raw = after[0].strip(".,;:!?，。；：！？")
        tok = tok_raw.lower()
        if tok in _UNITS:
            parts.append(tok_raw)
        elif tok and tok not in _STOPWORDS:
            parts.append(tok_raw)
    return " ".join(parts).strip()


def _context_word(text: str, start: int, end: int, n: int = 2) -> str:
    lo, hi = _sentence_bounds(text, start)
    keyword = text[start:end]

    if _is_cjk(keyword):
        return text[lo:hi].strip()[:60]

    before = text[lo:start].split()[-n:]
    after = text[end:hi].split()[:n]
    return " ".join(before + [keyword] + after).strip()


def _has_peer_token(ctx: str, keyword: str, vocabulary: list[str]) -> bool:
    kw_lower = keyword.lower()
    vocab_lower = {v.lower() for v in vocabulary}
    for w in re.split(r"[\s,，。.!?！？、;；:：]+", ctx):
        w_lower = w.lower()
        if len(w) < 2:
            continue
        if w_lower == kw_lower:
            continue
        if w_lower in vocab_lower:
            continue
        return True
    return False


def _find_enum_ranges(text: str) -> list[tuple[int, int]]:
    matches = list(_NUM.finditer(text))
    if len(matches) < 3:
        return []

    ranges: list[tuple[int, int]] = []
    i = 0
    while i < len(matches) - 2:
        prev_val = _to_int(matches[i].group())
        if prev_val is None:
            i += 1
            continue
        run_end = i
        for j in range(i + 1, min(i + 8, len(matches))):
            cur_val = _to_int(matches[j].group())
            if cur_val is None:
                break
            if cur_val == prev_val + 1:
                run_end = j
                prev_val = cur_val
            else:
                break
        if run_end - i >= 2:
            ranges.append((matches[i].start(), matches[run_end].end()))
            i = run_end + 1
        else:
            i += 1
    return ranges


def _to_int(s: str) -> int | None:
    s = s.rstrip("%")
    try:
        v = int(s)
    except ValueError:
        return None
    return v if 0 <= v <= 100 else None


def _in_ranges(pos: int, ranges: list[tuple[int, int]]) -> bool:
    return any(lo <= pos < hi for lo, hi in ranges)


def _is_meaningful_number(raw: str, m: re.Match, text: str) -> bool:
    if "." in raw or "," in raw:
        return True
    if raw.endswith("%"):
        return True
    try:
        v = int(raw.rstrip("%"))
    except ValueError:
        return False
    if v >= 10:
        return True
    tail = text[m.end():m.end() + 6]
    return any(u in tail for u in
               ["%", "$", "€", "¥", "元", "萬", "万", "千", "k", "K", "亿", "億"])


def extract_assertions(
    text: str, ref: str, source_type: str,
    time_range: tuple[float, float],
) -> list[dict]:
    if not text:
        return []

    out: list[dict] = []
    seen_claims: set[str] = set()
    seen_numbers: set[float] = set()

    def _add(claim: str, kind: str) -> None:
        claim = claim.strip()
        if len(claim) < 2 or claim in seen_claims:
            return
        seen_claims.add(claim)
        out.append({
            "claim": claim,
            "kind": kind,
            "ref": ref,
            "source_type": source_type,
            "time_range": list(time_range),
        })

    noise = _find_enum_ranges(text)

    for m in _NUM.finditer(text):
        if _in_ranges(m.start(), noise):
            continue
        if not _is_meaningful_number(m.group(), m, text):
            continue
        try:
            val = float(m.group().rstrip("%").replace(",", ""))
        except ValueError:
            continue
        if val in seen_numbers:
            continue
        seen_numbers.add(val)
        _add(_context_number(text, m.start(), m.end()), "number")

    for m in _COLOR_RE.finditer(text):
        ctx = _context_word(text, m.start(), m.end(), n=2)
        if _has_peer_token(ctx, m.group(), _COLORS):
            _add(ctx, "color")

    for m in _DIR_RE.finditer(text):
        ctx = _context_word(text, m.start(), m.end(), n=2)
        if _has_peer_token(ctx, m.group(), _DIRECTIONS):
            _add(ctx, "direction")

    for m in _PAIRED_QUOTE.finditer(text):
        name = next((g for g in m.groups() if g), "").strip()
        if 2 <= len(name) <= 30 and not name.endswith((".", ",", "?", "!")):
            _add(name, "name")

    return out


def _extractive(text: str, max_chars: int) -> str:
    sents = re.split(r"(?<=[。！？.!?])\s*", text)
    out = ""
    for s in sents:
        if len(out) + len(s) > max_chars:
            break
        out += s
    return out.strip() or text[:max_chars]


# ---------- LLM JSON 容錯（含搶救） ----------

def _parse_llm_json(resp: str) -> dict | None:
    """4B 模型返回的 JSON 常見問題：程式塊包裹、前後說明文字、尾部截斷。
    逐級搶救：直接解析 → 剝離代碼塊 → 提取 {...} → 逐行試 → 正則搶救 summary/assertions。
    """
    if not resp:
        return None

    stripped = resp.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        body = []
        for ln in lines[1:]:
            if ln.strip().startswith("```"):
                break
            body.append(ln)
        stripped = "\n".join(body).strip()

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    lo = resp.find("{")
    hi = resp.rfind("}")
    if lo != -1 and hi > lo:
        try:
            return json.loads(resp[lo:hi + 1])
        except json.JSONDecodeError:
            pass

    for line in resp.splitlines():
        line = line.strip().rstrip(",;")
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    # 搶救：從截斷/半合法的 JSON 裡提取 summary 和已完成的 assertions
    salvaged: dict = {}

    m_sum = re.search(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)"', resp)
    if m_sum:
        try:
            salvaged["summary"] = json.loads(f'"{m_sum.group(1)}"')
        except json.JSONDecodeError:
            salvaged["summary"] = m_sum.group(1)

    m_asserts = re.search(r'"assertions"\s*:\s*(\[.*)', resp, re.S)
    if m_asserts:
        arr_text = m_asserts.group(1).strip()
        # 剝掉尾部程式塊標記
        arr_text = re.sub(r"```\s*$", "", arr_text).rstrip()

        # 先嚐試完整解析
        try:
            parsed = json.loads(arr_text)
            if isinstance(parsed, list):
                salvaged["assertions"] = parsed
        except json.JSONDecodeError:
            pass

        # 從後往前找可閉合位置：候選必須結束於 `}`，補 `]` 後嘗試
        if "assertions" not in salvaged:
            for end in range(len(arr_text), 0, -1):
                if arr_text[end - 1] != "}":
                    continue
                candidate = arr_text[:end] + "]"
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, list):
                        salvaged["assertions"] = parsed
                        break
                except json.JSONDecodeError:
                    continue

    if salvaged.get("summary"):
        return salvaged
    return None


# ---------- LLM 後置過濾 ----------

_ABSTRACT_WORDS = {
    "smart", "inspirational", "brilliant", "important", "great", "good",
    "bad", "amazing", "awesome", "wonderful", "fantastic", "excellent",
    "terrible", "horrible", "beautiful", "ugly", "nice", "cool",
    "interesting", "boring", "funny", "serious", "happy", "sad",
    "big", "small", "large", "little", "huge", "tiny",
    "many", "few", "some", "several", "various", "multiple",
    "something", "anything", "everything", "nothing",
    "essential", "critical", "key", "core",
    "better", "best", "worse", "worst",
    "perfect", "intellectual", "broader", "personal", "real",
    "different", "similar", "general", "specific",
}

_NUMBER_WORDS = {
    "zero", "one", "two", "three", "four", "five", "six", "seven",
    "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
    "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty",
    "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
    "hundred", "thousand", "million", "billion",
    "half", "quarter", "third", "fourth", "fifth",
}

_TIMESTAMP_RE = re.compile(r"^\d+(?:\.\d+)?s$|^\d+:\d+$|^\d+:\d+:\d+$")


def _effective_length(claim: str) -> int:
    """CJK 字符權重 2，其他字符權重 1——近似"信息量"。
    中文 2 字詞（如"襯衫"、"眼鏡"）語義完整，不應按英文字符數過濾。
    """
    cjk = sum(1 for c in claim if "\u4e00" <= c <= "\u9fff")
    return cjk * 2 + (len(claim) - cjk)


def _is_enumeration(claim: str) -> bool:
    nums = re.findall(r"\b\d+\b", claim)
    if len(nums) < 3:
        return False
    try:
        vals = [int(n) for n in nums]
    except ValueError:
        return False
    consecutive = sum(1 for i in range(len(vals) - 1) if vals[i + 1] == vals[i] + 1)
    return consecutive >= len(vals) - 2


def _filter_llm_assertions(assertions: list[dict], max_count: int = 6) -> list[dict]:
    """後置過濾：
    1. 丟棄時間戳洩漏（"307.5s"）
    2. 丟棄純枚舉序列（"1, 2, 3, 4, 5"）
    3. 丟棄純英文數詞（"one", "zero", "half"）
    4. 丟棄 claim 全是抽象詞的斷言
    5. 丟棄信息量過低的非數字斷言（用 _effective_length 判斷，CJK 加權）
    6. 去重 + 截斷到 max_count
    """
    kept: list[dict] = []
    seen: set[str] = set()
    for a in assertions:
        claim = (a.get("claim") or "").strip()
        if not claim or claim in seen:
            continue
        kind = a.get("kind", "other")

        if _TIMESTAMP_RE.match(claim):
            continue
        if _is_enumeration(claim):
            continue
        if claim.lower().strip(".,;:!?") in _NUMBER_WORDS:
            continue

        if kind != "number":
            words = [w.lower().strip(".,;:!?") for w in claim.split()]
            # 抽象詞過濾：只對英文有效，中文詞不在 _ABSTRACT_WORDS 裡，天然通過
            if words and all(w in _ABSTRACT_WORDS or len(w) < 3 for w in words):
                # 但要排除純中文的 claim（"words" 裡可能有中文被誤判）
                if not _is_cjk(claim):
                    continue
            # 有效長度檢查：CJK 加權，閾值 4
            if _effective_length(claim) < 4:
                continue

        seen.add(claim)
        kept.append(a)
        if len(kept) >= max_count:
            break
    return kept


def summarize_window(
    ctx: AppContext, run_id: str, video_id: str, *,
    time_range: tuple[float, float],
    text: str, ref: str, source_type: str = "official_subtitle",
    max_chars: int = 220,
) -> dict:
    """返回 {summary, assertions, raw_ref, source_type, time_range, via}。"""
    if ctx.router.available("local_summary"):
        prompt = f"錨點：{ref}\n字幕：\n{text}"
        resp = ctx.router.call(
            "local_summary", run_id,
            messages=[
                {"role": "system", "content": SYSTEM_LOCAL_SUMMARY},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1200,
            temperature=0.1,
        )
        if resp:
            data = _parse_llm_json(resp)
            if data and isinstance(data.get("summary"), str):
                summary = data["summary"].strip() or _extractive(text, max_chars)
                assertions = data.get("assertions") or []
                normalized: list[dict] = []
                for a in assertions:
                    if not isinstance(a, dict) or not a.get("claim"):
                        continue
                    kind = a.get("kind", "other")
                    if kind not in {"number", "color", "name", "direction", "other"}:
                        kind = "other"
                    normalized.append({
                        "claim": str(a["claim"]).strip(),
                        "kind": kind,
                        "ref": a.get("ref") or ref,
                        "source_type": a.get("source_type") or source_type,
                        "time_range": a.get("time_range") or list(time_range),
                    })

                normalized = _filter_llm_assertions(normalized)

                if summary or normalized:
                    if not normalized:
                        normalized = extract_assertions(text, ref, source_type, time_range)
                    return {
                        "summary": summary or _extractive(text, max_chars),
                        "assertions": normalized,
                        "raw_ref": ref,
                        "source_type": source_type,
                        "time_range": list(time_range),
                        "via": "llm",
                    }

    return {
        "summary": _extractive(text, max_chars),
        "assertions": extract_assertions(text, ref, source_type, time_range),
        "raw_ref": ref,
        "source_type": source_type,
        "time_range": list(time_range),
        "via": "extractive",
    }
