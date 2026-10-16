from services.live_media.gpu_backend_runtime import GPUBackendStatus
from services.live_media.readiness import LiveMediaReadiness
from services.live_media.webrtc_runtime import WebRTCRuntimeStatus


def test_readiness_requires_webrtc_and_gpu():
    ready = LiveMediaReadiness(
        WebRTCRuntimeStatus("aiortc", True, "ok"),
        GPUBackendStatus(True, False, False),
    )
    assert ready.runtime_ready

    no_gpu = LiveMediaReadiness(
        WebRTCRuntimeStatus("aiortc", True, "ok"),
        GPUBackendStatus(False, False, False),
    )
    assert not no_gpu.runtime_ready

    no_webrtc = LiveMediaReadiness(
        WebRTCRuntimeStatus("none", False, "missing"),
        GPUBackendStatus(True, False, False),
    )
    assert not no_webrtc.runtime_ready


def test_installed_cpu_packages_do_not_report_gpu_readiness(monkeypatch):
    import services.live_media.gpu_backend_runtime as runtime

    monkeypatch.setattr(runtime, "find_spec", lambda name: object())
    monkeypatch.setattr(
        runtime,
        "import_module",
        lambda name: type(
            "Runtime",
            (),
            {
                "cuda": type("Cuda", (), {"is_available": staticmethod(lambda: False)})(),
                "get_available_providers": staticmethod(lambda: ["CPUExecutionProvider"]),
            },
        )(),
    )

    status = runtime.detect_gpu_backends()

    assert status == GPUBackendStatus(False, False, False)


def test_cuda_and_gpu_onnx_providers_are_reported_as_available(monkeypatch):
    import services.live_media.gpu_backend_runtime as runtime

    providers = ["CPUExecutionProvider", "CUDAExecutionProvider", "TensorrtExecutionProvider"]
    monkeypatch.setattr(runtime, "find_spec", lambda name: object())
    monkeypatch.setattr(
        runtime,
        "import_module",
        lambda name: type(
            "Runtime",
            (),
            {
                "cuda": type("Cuda", (), {"is_available": staticmethod(lambda: True)})(),
                "get_available_providers": staticmethod(lambda: providers),
            },
        )(),
    )

    status = runtime.detect_gpu_backends()

    assert status == GPUBackendStatus(True, True, True)
