import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from services.live_media import prefetch_facefusion_models as prefetch
from services.live_media.runpod_facefusion_worker import build_facefusion_command

COMMON_MODULES = (
    "content_analyser",
    "face_classifier",
    "face_detector",
    "face_landmarker",
    "face_masker",
    "face_recognizer",
    "voice_extractor",
)


@pytest.fixture
def upstream(monkeypatch, tmp_path):
    """Model the pinned public APIs without downloading assets or loading ONNX."""
    state = {}
    modules = []
    assets = {}
    for name in (*COMMON_MODULES, "face_swapper"):
        hash_path = tmp_path / f"{name}.hash"
        source_path = tmp_path / f"{name}.onnx"
        hashes = {name: {"path": str(hash_path)}}
        sources = {name: {"path": str(source_path)}}
        assets[name] = hash_path, source_path
        if name in ("face_classifier", "face_recognizer", "face_swapper"):
            module = SimpleNamespace(
                get_model_options=Mock(return_value={"hashes": hashes, "sources": sources})
            )
        else:
            module = SimpleNamespace(collect_model_downloads=Mock(return_value=(hashes, sources)))
        modules.append(module)

    def download_selected():
        assert state["processors"] == ["face_swapper"]
        assert state["face_swapper_model"] == "ghost_1_256"
        for hash_path, source_path in assets.values():
            hash_path.write_bytes(b"expected")
            source_path.write_bytes(b"expected")
        return True

    processor = modules[-1]
    processor.pre_check = Mock(side_effect=download_selected)
    processor.get_common_modules = Mock(return_value=modules[:-1])
    loader = Mock(return_value=processor)

    def validate(paths):
        valid, invalid = [], []
        for path in paths:
            p = Path(path)
            (valid if p.is_file() and p.read_bytes() == b"expected" else invalid).append(path)
        return valid, invalid

    root = ModuleType("facefusion")
    root.choices = SimpleNamespace(download_providers=["github", "huggingface"])
    root.state_manager = SimpleNamespace(init_item=state.__setitem__)
    downloads = ModuleType("facefusion.download")
    downloads.validate_hash_paths = Mock(side_effect=validate)
    downloads.validate_source_paths = Mock(side_effect=validate)
    core = ModuleType("facefusion.processors.core")
    core.load_processor_module = loader
    for name, module in (
        ("facefusion", root),
        ("facefusion.download", downloads),
        ("facefusion.processors", ModuleType("facefusion.processors")),
        ("facefusion.processors.core", core),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    return SimpleNamespace(
        state=state, processor=processor, modules=modules, assets=assets,
        loader=loader, downloads=downloads,
    )


def test_only_configured_processor_and_selected_common_models_are_prefetched(upstream):
    prefetch.prefetch_models()

    upstream.loader.assert_called_once_with("face_swapper")
    upstream.processor.pre_check.assert_called_once_with()
    assert upstream.state == {
        "processors": ["face_swapper"],
        "face_swapper_model": "ghost_1_256",
        "face_detector_model": "yolo_face",
        "face_landmarker_model": "2dfan4",
        "face_occluder_model": "xseg_1",
        "face_parser_model": "bisenet_resnet_34",
        "voice_extractor_model": "kim_vocal_2",
        "download_providers": ["github", "huggingface"],
        "log_level": "error",
    }
    assert upstream.downloads.validate_hash_paths.call_count == 8
    assert upstream.downloads.validate_source_paths.call_count == 8
    for module in upstream.modules:
        if hasattr(module, "collect_model_downloads"):
            module.collect_model_downloads.assert_called_once_with()
        else:
            module.get_model_options.assert_called_once_with()
    command = build_facefusion_command(Path("source"), Path("target"), Path("output"))
    assert command[command.index("--processors") + 1] == "face_swapper"
    selected_model = command[command.index("--face-swapper-model") + 1]
    assert selected_model == upstream.state["face_swapper_model"]


def test_failed_upstream_precheck_aborts_build(upstream):
    upstream.processor.pre_check.side_effect = None
    upstream.processor.pre_check.return_value = False
    with pytest.raises(RuntimeError, match="Required model prefetch failed"):
        prefetch.prefetch_models()
    upstream.downloads.validate_source_paths.assert_not_called()


@pytest.mark.parametrize("module_name", (*COMMON_MODULES, "face_swapper"))
@pytest.mark.parametrize("failure", ("missing_hash", "missing_source", "corrupt_source"))
def test_build_rejects_missing_or_corrupt_assets_after_successful_precheck(
    upstream, module_name, failure
):
    download = upstream.processor.pre_check.side_effect

    def incomplete_download():
        download()
        hash_path, source_path = upstream.assets[module_name]
        if failure == "missing_hash":
            hash_path.unlink()
        elif failure == "missing_source":
            source_path.unlink()
        else:
            source_path.write_bytes(b"corrupt")
        return True

    upstream.processor.pre_check.side_effect = incomplete_download
    with pytest.raises(RuntimeError, match="Required model assets are unavailable"):
        prefetch.prefetch_models()


def test_empty_selected_asset_manifest_aborts_build(upstream):
    upstream.processor.get_model_options.return_value = {"hashes": {}, "sources": {}}
    with pytest.raises(RuntimeError, match="Required model assets are unavailable"):
        prefetch.prefetch_models()


def test_entrypoint_fails_closed_without_emitting_arbitrary_exception_details(monkeypatch, capsys):
    def fail():
        raise RuntimeError("arbitrary untrusted detail")

    monkeypatch.setattr(prefetch, "prefetch_models", fail)
    with pytest.raises(SystemExit) as error:
        prefetch.main()
    assert str(error.value) == "Required FaceFusion model prefetch failed."
    assert error.value.__suppress_context__
    assert capsys.readouterr() == ("", "")


def test_docker_prefetch_is_bounded_and_build_workflow_tracks_script():
    root = Path(__file__).resolve().parents[1]
    docker = (root / "services/live_media/Dockerfile.runpod").read_text()
    workflow = (root / ".github/workflows/runpod-worker-image.yml").read_text()
    assert "COPY services/live_media/prefetch_facefusion_models.py /opt/facefusion/" in docker
    assert "RUN cd /opt/facefusion && timeout 1800s python prefetch_facefusion_models.py" in docker
    assert docker.index("python install.py") < docker.index("timeout 1800s python")
    assert "force-download" not in docker
    assert "services/live_media/prefetch_facefusion_models.py" in workflow
