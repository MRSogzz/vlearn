from app.evidence.arbiter import arbitrate
from app.schemas import EvidenceBundle, SourceType


def _bundle():
    return EvidenceBundle(id="b1", video_id="v1", time_range=(0, 10), summary_ids=[])


def test_resolved_when_top_dominates():
    r = arbitrate(_bundle(), [
        {"source_type": SourceType.OFFICIAL_SUBTITLE, "confidence": 1.0, "quality_flags": []},
        {"source_type": SourceType.DANMAKU, "confidence": 1.0, "quality_flags": []},
    ])
    assert r.status == "resolved"
    assert r.adopted_source == SourceType.OFFICIAL_SUBTITLE.value


def test_unresolved_when_two_strong_sources():
    r = arbitrate(_bundle(), [
        {"source_type": SourceType.OFFICIAL_SUBTITLE, "confidence": 1.0, "quality_flags": []},
        {"source_type": SourceType.PLATFORM_METADATA, "confidence": 1.0, "quality_flags": []},
    ])
    assert r.status == "unresolved"
    assert r.keep_both_versions is True


def test_empty_summaries_unresolved():
    r = arbitrate(_bundle(), [])
    assert r.status == "unresolved"
