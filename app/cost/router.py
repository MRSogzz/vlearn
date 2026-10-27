"""模型路由 + LLM 调用。

- route(stage) 从 models.yaml 读出 (provider, model, config)
- api_key 支持两种写法（优先级：直写 > 环境变量）
- 模型名支持两种写法（优先级：served_model_name > key）
- call(...) 真调用（OpenAI 兼容），无 key 或失败时返回 None
- 计费按配置单价 + 峰值时段

带图片的调用（llama.cpp / Qwen3-VL 等）：
- 走流式（stream=True）—— 非流式 + vision 有 bug
- 传 reasoning_control + reasoning_format + backend_sampling=False
- 图片放 text 之前（chat template 对顺序敏感）

4B 模型常见问题：
- content 字段为空但 reasoning_content 里有答案（model 把答案写进了 thinking）
- 本模块会自动从 reasoning_content 抢救——见 _extract_from_reasoning

日志：所有失败路径都会写 log.warning，便于诊断空 content / 超时 / context 超限。
"""
from __future__ import annotations
import base64
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from app.cost.ledger import CostLedger

log = logging.getLogger(__name__)


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

    def route(self, stage: str) -> Optional[ModelRef]:
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
             images: Optional[list[str]] = None,
             temperature: float = 0.2,
             max_tokens: int = 1024) -> Optional[str]:
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
            # llama.cpp 的完整 reasoning 控制字段
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
        except Exception as e:
            log.warning(
                "router.call %s raised: %s: %s",
                stage, type(e).__name__, e, exc_info=True,
            )
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

    def _call_blocking(self, ref: ModelRef, payload: dict) -> Optional[str]:
        """非流式调用（纯文本）。所有失败路径都打日志。

        4B 模型有时把答案写进 reasoning_content 而 content 为空，
        这种情况下从 reasoning_content 提取最后一段作为兜底。
        """
        try:
            with httpx.Client(timeout=300) as client:
                r = client.post(
                    f"{ref.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {ref.api_key}",
                             "Content-Type": "application/json"},
                    json=payload,
                )
            if r.status_code != 200:
                log.warning(
                    "LLM %s status=%s body=%s",
                    ref.model, r.status_code, r.text[:300],
                )
                return None
            data = r.json()
            choices = data.get("choices", [])
            if not choices:
                log.warning(
                    "LLM %s returned empty choices: %s",
                    ref.model, str(data)[:500],
                )
                return None
            message = choices[0].get("message", {})
            content = (message.get("content") or "").strip()

            # ── 关键：content 空时，从 reasoning_content 抢救 ──
            if not content:
                reasoning = (
                    message.get("reasoning_content")
                    or message.get("reasoning")
                    or ""
                )
                if reasoning:
                    log.info(
                        "LLM %s content empty, extracting from reasoning_content (len=%d)",
                        ref.model, len(reasoning),
                    )
                    content = self._extract_from_reasoning(reasoning)

            if not content:
                log.warning(
                    "LLM %s returned empty content AND empty reasoning. "
                    "message_keys=%s finish_reason=%s",
                    ref.model,
                    list(message.keys()),
                    choices[0].get("finish_reason"),
                )
                return None

            usage = data.get("usage", {})
            payload["_usage"] = usage
            return content
        except Exception as e:
            log.warning(
                "LLM %s raised: %s: %s",
                ref.model, type(e).__name__, e, exc_info=True,
            )
            return None

    @staticmethod
    def _extract_from_reasoning(reasoning: str) -> str:
        """从 reasoning_content 提取最后一段作为答案。

        4B 模型在 reasoning 末尾常会输出 "Draft:" / "Output:" / "Final Answer:"
        之类标记，后面才是真正的答案。如果没有标记，就取最后一段非空段落。
        返回长度上限 500 字，避免把整段 thinking 当成答案。
        """
        if not reasoning or not reasoning.strip():
            return ""

        # 优先找显式标记
        markers = [
            "Draft:", "Draft Answer:", "Final Answer:", "Final:",
            "Output:", "Answer:", "Overview:", "Summary:",
        ]
        for marker in markers:
            idx = reasoning.rfind(marker)
            if idx != -1:
                tail = reasoning[idx + len(marker):].strip()
                if tail:
                    return tail[:500]

        # 没有标记，取最后一段非空
        paragraphs = [p.strip() for p in reasoning.split("\n\n") if p.strip()]
        if not paragraphs:
            return ""
        last = paragraphs[-1]
        return last[:500]

    def _call_stream(self, ref: ModelRef, payload: dict) -> Optional[str]:
        """流式调用（带图片时必须用）。"""
        chunks: list[str] = []
        try:
            with httpx.stream(
                "POST",
                f"{ref.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {ref.api_key}",
                         "Content-Type": "application/json"},
                json=payload,
                timeout=300,
            ) as r:
                if r.status_code != 200:
                    log.warning(
                        "LLM stream %s status=%s", ref.model, r.status_code,
                    )
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
        except Exception as e:
            log.warning(
                "LLM stream %s raised: %s: %s",
                ref.model, type(e).__name__, e, exc_info=True,
            )
            return None
        return "".join(chunks) if chunks else ""

    def _build_messages(self, messages: list[dict],
                        images: Optional[list[str]]) -> list[dict]:
        """把图片合入最后一条 user message（image 在前，text 在后）。"""
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
                    {"type": "text", "text": "请基于以上图片回答。"},
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

    def _load_image_data(self, path: str) -> Optional[str]:
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