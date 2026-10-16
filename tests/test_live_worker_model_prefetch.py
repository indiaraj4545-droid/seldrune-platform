from pathlib import Path


def test_live_worker_image_prefetches_facefusion_models_during_build():
    dockerfile = (
        Path(__file__).resolve().parents[1]
        / "services"
        / "live_media"
        / "Dockerfile.runpod-live"
    ).read_text(encoding="utf-8")
    source_copy = dockerfile.index("COPY services/live_media /app/services/live_media")
    prefetch = dockerfile.index(
        "RUN timeout 1800s python -m services.live_media.prefetch_facefusion_models"
    )
    runtime_command = dockerfile.index(
        "CMD [\"python\", \"-m\", \"services.live_media.runpod_live_worker\"]"
    )

    assert source_copy < prefetch < runtime_command
