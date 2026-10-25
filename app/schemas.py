from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field


class SourceType(str, Enum):
    OFFICIAL_SUBTITLE = "official_subtitle"
    PLATFORM_METADATA = "platform_metadata"
    KEYFRAME_OCR = "keyframe_ocr"      # 畫面經 OCR 轉錄
    KEYFRAME_VLM = "keyframe_vlm"      # 畫面經 VLM caption
    KEYFRAME = "keyframe"               # deprecated alias（兼容舊數據）
    ASR = "asr"
    DANMAKU = "danmaku"
    COMMENT = "comment"


class QualityFlag(str, Enum):
    BLURRY = "blurry"
    TRANSITION = "transition"
    LOW_RES = "low_res"
    LOW_ASR_CONF = "low_asr_conf"
    DUPLICATE = "duplicate"
    VLM_HALLUCINATION_RISK = "vlm_hallucination_risk"   # 新增


class SourceSegment(BaseModel):
    id: str
    video_id: str
    source_type: SourceType
    start: float
    end: float
    text: str = ""
    confidence: float = 1.0
    reliability: int = 3
    quality_flags: list[QualityFlag] = Field(default_factory=list)


class Keyframe(BaseModel):
    id: str
    video_id: str
    timestamp: float
    trigger_type: Literal[
        "scene_change",
        "fixed_interval",
        "semantic_request",
        "seek_margin",        # seek 場景下的 margin 選幀
        "danmaku_peak",       # 彈幕密度峰值
        "user_request",       # 用戶點名
        "probe",              # 探針幀
        "fallback",           # 保底幀（訪談類）
        "conditional",        # 條件補幀（下三分之一字幕條）
    ]
    sharpness_score: float = 0.0
    quality_flags: list[QualityFlag] = Field(default_factory=list)
    image_path: Optional[str] = None
    prev_scene_boundary: Optional[float] = None
    next_scene_boundary: Optional[float] = None


class Assertion(BaseModel):
    claim: str
    kind: Literal["number", "color", "name", "direction", "other"] = "other"
    ref: str = ""
    source_type: SourceType = SourceType.OFFICIAL_SUBTITLE
    time_range: tuple[float, float] = (0.0, 0.0)


class WindowSummary(BaseModel):
    id: str
    video_id: str
    time_range: tuple[float, float]
    source_type: SourceType
    text: str = ""
    summary: str = ""
    assertions: list[Assertion] = Field(default_factory=list)
    confidence: float = 1.0
    raw_refs: list[str] = Field(default_factory=list)


class EvidenceBundle(BaseModel):
    id: str
    video_id: str
    time_range: tuple[float, float]
    summary_ids: list[str]
    status: Literal["consistent", "suspect", "conflict", "pending"] = "pending"


class ConflictRecord(BaseModel):
    id: str
    bundle_id: str
    sources: list[str]
    status: Literal["resolved", "unresolved"]
    adopted_source: Optional[str] = None
    reason: str = ""
    confidence: Literal["high", "medium", "low"] = "medium"
    keep_both_versions: bool = True
    resolution_level: Literal["summary", "raw"] = "summary"


class FinalSummary(BaseModel):
    id: str
    video_id: str
    report_md: str
    assertions: list[Assertion] = Field(default_factory=list)
    unresolved_conflicts: list[str] = Field(default_factory=list)
    created_at: datetime


class CostEntry(BaseModel):
    run_id: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    image_tokens: int = 0
    usd: float = 0.0
    is_peak: bool = False
    stage: str = ""     # probe | scan | keyframe | backtrace | local_summary | final_summary | triage


class Correction(BaseModel):
    id: str
    target_assertion_ref: str
    old_value: str
    new_value: str
    user_note: str = ""
    created_at: datetime
