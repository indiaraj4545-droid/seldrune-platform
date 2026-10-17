"""Calling-console routing and boundaries; browser lifecycle is tested with Node."""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


@pytest.mark.parametrize("path", ["/camera", "/camera/output"])
def test_camera_pages_serve_without_caching_and_share_same_origin(path):
    response = TestClient(app).get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'self'" in response.headers["content-security-policy"]
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_console_reuses_authorized_studio_and_labels_meeting_app_requirements():
    response = TestClient(app).get("/camera")

    assert 'id="live-studio"' in response.text
    assert 'src="/media"' in response.text
    assert "both approved face and voice profiles" in response.text
    assert "OBS Virtual Camera" in response.text
    assert "Zoom" in response.text and "Teams" in response.text and "Google Meet" in response.text
    assert "Mobile apps cannot select this page as a system camera" in response.text
    assert "camera=(self)" in response.headers["permissions-policy"]


def test_projection_has_no_device_or_api_permissions_and_keeps_visible_disclosure():
    response = TestClient(app).get("/camera/output")

    assert "camera=(), microphone=(), display-capture=()" == response.headers["permissions-policy"]
    assert 'id="output-disclosure" class="disclosure">AI MODIFIED' in response.text
    assert 'id="camera-output" autoplay muted playsinline hidden' in response.text
    assert "local-video" not in response.text
    assert "liveshell-mobile.js" not in response.text
    assert "/media" not in response.text
    assert "seldruneToken" not in response.text


@pytest.mark.parametrize(
    "asset", ["face-camera.css", "face-camera-console.js", "face-camera-output.js"]
)
def test_console_assets_available_from_the_existing_static_mount(asset):
    response = TestClient(app).get(f"/console-assets/{asset}")

    assert response.status_code == 200
    assert response.content


def test_existing_studio_links_to_the_separate_calling_console():
    response = TestClient(app).get("/media")

    assert 'href="/camera"' in response.text
