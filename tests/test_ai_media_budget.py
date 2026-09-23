import pytest

from backend.app.core.config import Settings
from backend.app.services.ai_media_budget import (
    build_media_cost_policy,
    estimate_sora2_cost_usd,
)


def test_media_policy_is_low_cost_by_default() -> None:
    settings = Settings()
    policy = build_media_cost_policy(settings)

    assert policy.image_model == "gpt-image-2"
    assert policy.image_quality == "low"
    assert policy.image_job_max_usd <= 0.08
    assert policy.video_model == "sora-2"
    assert policy.video_resolution == "720p"
    assert policy.video_default_seconds == 4
    assert policy.video_job_max_usd <= 0.40
    assert policy.prefer_batch is True


def test_media_policy_tightens_in_conservation_mode() -> None:
    settings = Settings()
    policy = build_media_cost_policy(settings, monthly_utilization=0.85)

    assert policy.image_job_max_usd <= 0.04
    assert policy.video_job_max_usd <= 0.20


def test_sora2_cost_estimate_prefers_batch_for_background_video() -> None:
    assert estimate_sora2_cost_usd(4, batch=False) == pytest.approx(0.40)
    assert estimate_sora2_cost_usd(4, batch=True) == pytest.approx(0.20)
