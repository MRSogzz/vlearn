"""模型路由 + LLM 調用。

關鍵設計：
- 帶圖片的調用走流式（stream=True）
  llama.cpp 在非流式 + vision 組合下有 bug（輸出退化為重複字符）

- 帶圖片的調用必須傳完整的 llama.cpp WebUI 擴展字段：
    reasoning_control: True      — 讓服務端分離 thinking block
    reasoning_format: "auto"     — 自動格式化
    backend_sampling: False      — 禁用服務端默認採樣（關鍵！）
    return_progress: True        — 返回進度
    timings_per_token: True      — 返回 token 計時
    sse_ping_interval: 1         — SSE 心跳間隔

  不加這些字段時，`llmserver.sh` 的 `--reasoning-budget 16384` 會強制
  生成 thinking token，客戶端拿到的 content 是被汙染的結果（吐 '/'）。

- 圖片放在 text 之前（Qwen3-VL chat template 對順序敏感）
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.cost.ledger import CostLedger


@dataclass
class ModelRef:
    provider: str
    model: str
    base_url: str
    api_key: str
    input_usd: float
    output_usd: float
    image_token_cap: int
    supports_vision: bool
    is_peak: bool


def _is_peak(now_utc: datetime, windows: list[str]) -> bool:
    hh = now_utc.hour
    for w in windows:
        try:
            a, b = w.split("-")
            ha, hb = int(a[:2]), int(b[:2])
        except Exception:
            continue
        if ha <= hh < hb:
            return True
    return False


class ModelRouter:
    def __init__(self, models_cfg: dict, peak_hours: list[str], ledger: CostLedger):
        self.cfg = models_cfg
        self.peak_hours = peak_hours or []
        self.ledger = ledger

    def route(self, stage: str) -> ModelRef | None:
        r = self.cfg.get("routing", {}).get(stage)
        if not r:
            return None
        provider_name, model_name = r["provider"], r["model"]
        prov = self.cfg["providers"].get(provider_name)
        if not prov:
            return None
        model_cfg = prov["models"].get(model_name)
        if not model_cfg:
            return None

        api_key = (prov.get("api_key")
                   or os.getenv(prov.get("api_key_env", ""), "")
                   or "")
        served_name = model_cfg.get("served_model_name") or model_name
        is_peak = _is_peak(datetime.now(timezone.utc), self.peak_hours)
        in_usd = float(model_cfg.get("input_usd", 0))
        out_usd = float(model_cfg.get("output_usd", 0))
        if not is_peak:
            in_usd = float(model_cfg.get("offpeak_input_usd", in_usd))
            out_usd = float(model_cfg.get("offpeak_output_usd", out_usd))

        return ModelRef(
            provider=provider_name,
            model=served_name,
            base_url=prov["base_url"],
            api_key=api_key,
            input_usd=in_usd,
            output_usd=out_usd,
            image_token_cap=int(model_cfg.get("image_token_cap", 384)),
            supports_vision=bool(model_cfg.get("supports_vision", False)),
            is_peak=is_peak,
        )

    def available(self, stage: str) -> bool:
        ref = self.route(stage)
        return bool(ref and ref.api_key)

    def call(self, stage: str, run_id: str, *,
             messages: list[dict],
             images: list[str] | None = None,
             temperature: float = 0.2,
             max_tokens: int = 1024) -> str | None:
        """返回文本；無 key 或失敗時返回 None（調用方降級）。

        帶圖片的調用強制加 llama.cpp WebUI 的完整字段集：
        - stream=True
        - reasoning_control=True + reasoning_format="auto"（分離 thinking）
        - backend_sampling=False（禁用服務端默認採樣，避免 thinking 汙染）
        - return_progress / timings_per_token / sse_ping_interval（WebUI 兼容）
        """
        ref = self.route(stage)
        if not ref or not ref.api_key:
            return None
        if images and not ref.supports_vision:
            images = None

        payload_msgs = self._build_messages(messages, images)
        use_stream = bool(images)

        payload: dict = {
            "model": ref.model,
            "messages": payload_msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if images:
            # ★ 關鍵的 6 個字段——缺一個都會導致 thinking token 汙染輸出
            payload["reasoning_control"] = True
            payload["reasoning_format"] = "auto"
            payload["backend_sampling"] = False
            payload["return_progress"] = True
            payload["timings_per_token"] = True
            payload["sse_ping_interval"] = 1

        if use_stream:
            payload["stream"] = True

        try:
            if use_stream:
                text = self._call_stream(ref, payload)
            else:
                text = self._call_blocking(ref, payload)
        except Exception:
            return None

        if text is None:
            return None

        usage = payload.get("_usage") or {}
        in_tok = int(usage.get("prompt_tokens", 0))
        out_tok = int(usage.get("completion_tokens", 0))
        img_tok = len(images) * ref.image_token_cap if images else 0
        usd = (in_tok / 1_000_000) * ref.input_usd \
            + (out_tok / 1_000_000) * ref.output_usd \
            + (img_tok / 1_000_000) * ref.input_usd
        self.ledger.record(run_id, ref.provider, ref.model,
                           input_tokens=in_tok, output_tokens=out_tok,
                           image_tokens=img_tok, usd=usd,
                           is_peak=ref.is_peak, stage=stage)
        return text

    def _call_blocking(self, ref: ModelRef, payload: dict) -> str | None:
        with httpx.Client(timeout=300) as client:
            r = client.post(
                f"{ref.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {ref.api_key}",
                         "Content-Type": "application/json"},
                json=payload,
            )
        if r.status_code != 200:
            return None
        data = r.json()
        usage = data.get("usage", {})
        payload["_usage"] = usage
        return data["choices"][0]["message"].get("content") or ""

    def _call_stream(self, ref: ModelRef, payload: dict) -> str | None:
        chunks: list[str] = []
        with httpx.stream(
            "POST",
            f"{ref.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {ref.api_key}",
                     "Content-Type": "application/json"},
            json=payload,
            timeout=300,
        ) as r:
            if r.status_code != 200:
                return None
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
                delta = choices[0].get("delta", {})
                content = delta.get("content")
                if content:
                    chunks.append(content)
        return "".join(chunks) if chunks else ""

    def _build_messages(self, messages: list[dict],
                        images: list[str] | None) -> list[dict]:
        """把圖片合入最後一條 user message。

        ★ image 必須在 text 之前
        Qwen3-VL 的 chat template 對 content 順序敏感。
        """
        if not images:
            return messages

        user_parts: list[dict] = []
        for p in images:
            data = self._load_image_data(p)
            if data:
                user_parts.append({
                    "type": "image_url",
                    "image_url": {"url": data},
                })
        if not user_parts:
            return messages

        out = [dict(m) for m in messages]

        last_user_idx = -1
        for i in range(len(out) - 1, -1, -1):
            if out[i].get("role") == "user":
                last_user_idx = i
                break

        if last_user_idx == -1:
            out.append({
                "role": "user",
                "content": [
                    *user_parts,
                    {"type": "text", "text": "請基於以上圖片回答。"},
                ],
            })
            return out

        original = out[last_user_idx].get("content", "")
        if isinstance(original, str):
            out[last_user_idx]["content"] = [
                *user_parts,
                {"type": "text", "text": original},
            ]
        elif isinstance(original, list):
            out[last_user_idx]["content"] = list(user_parts) + list(original)
        else:
            out[last_user_idx]["content"] = [
                *user_parts,
                {"type": "text", "text": str(original)},
            ]

        return out

    def _load_image_data(self, path: str) -> str | None:
        p = Path(path)
        if not p.exists():
            return None
        try:
            b = p.read_bytes()
        except Exception:
            return None
        suffix = p.suffix.lower().lstrip(".") or "jpeg"
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png",
                "webp": "webp", "gif": "gif"}.get(suffix, "jpeg")
        return f"data:image/{mime};base64,{base64.b64encode(b).decode()}"
