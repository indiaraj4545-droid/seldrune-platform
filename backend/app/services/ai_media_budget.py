from dataclasses import dataclass

from backend.app.core.config import Settings


@dataclass(frozen=True)
class MediaCostPolicy:
    image_model: str
    image_quality: str
    image_size: str
    image_job_max_usd: float
    video_model: str
    video_resolution: str
    video_default_seconds: int
    video_max_seconds: int
    video_job_max_usd: float
    prefer_batch: bool


def build_media_cost_policy(
    settings: Settings,
    *,
    monthly_utilization: float = 0.0,
) -> MediaCostPolicy:
    """Return low-cost defaults for future OpenAI image/video operations."""
    conservation = float(monthly_utilization) >= settings.ai_conservation_ratio
    image_budget = min(
        settings.ai_image_job_max_usd,
        0.04 if conservation else settings.ai_image_job_max_usd,
    )
    video_budget = min(
        settings.ai_video_job_max_usd,
        0.20 if conservation else settings.ai_video_job_max_usd,
    )
    return MediaCostPolicy(
        image_model="gpt-image-2",
        image_quality="low",
        image_size="1024x1024",
        image_job_max_usd=image_budget,
        video_model="sora-2",
        video_resolution="720p",
        video_default_seconds=settings.ai_video_default_seconds,
        video_max_seconds=settings.ai_video_max_seconds,
        video_job_max_usd=video_budget,
        prefer_batch=settings.ai_media_batch_preferred,
    )


def estimate_sora2_cost_usd(
    seconds: int,
    *,
    batch: bool,
) -> float:
    """Estimate Sora 2 720p generation cost using current configured public rate."""
    duration = max(0, int(seconds))
    rate_per_second = 0.05 if batch else 0.10
    return round(duration * rate_per_second, 4)
