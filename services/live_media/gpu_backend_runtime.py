"""Runtime detection for optional cloud GPU inference providers."""
from dataclasses import dataclass
from importlib import import_module
from importlib.util import find_spec


@dataclass(frozen=True)
class GPUBackendStatus:
    cuda_available: bool
    onnx_available: bool
    tensorrt_available: bool


def detect_gpu_backends() -> GPUBackendStatus:
    """Report usable GPU backends, not merely installed Python packages."""
    cuda_available = False
    if find_spec("torch") is not None:
        try:
            cuda_available = bool(import_module("torch").cuda.is_available())
        except (ImportError, OSError, RuntimeError, AttributeError):
            pass

    providers: set[str] = set()
    if find_spec("onnxruntime") is not None:
        try:
            providers = set(import_module("onnxruntime").get_available_providers())
        except (ImportError, OSError, RuntimeError, AttributeError):
            pass

    onnx_available = bool(providers & {"CUDAExecutionProvider", "TensorrtExecutionProvider"})
    tensorrt_available = (
        find_spec("tensorrt") is not None and "TensorrtExecutionProvider" in providers
    )
    return GPUBackendStatus(
        cuda_available=cuda_available,
        onnx_available=onnx_available,
        tensorrt_available=tensorrt_available,
    )
