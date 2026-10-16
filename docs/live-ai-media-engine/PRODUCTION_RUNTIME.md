# Production runtime boundary

The Live AI Media Engine core remains dependency-light. Real deployments add
optional media/GPU packages in the dedicated media image rather than forcing
them into the Seldrune control-plane environment.

Runtime detection reports whether a supported WebRTC implementation and a GPU
inference backend are available. PyTorch must report CUDA available, or ONNX
Runtime must expose its CUDA/TensorRT execution provider; an installed CPU-only
package does not count. The STI `runtime_ready` value is only this dependency
capability signal. It does not prove a reachable GPU worker, loaded production
models, profile authorization, TURN service, transformed output, or a successful
phone call. Those require retained deployment and session evidence.

The intended next deployment image will provide:

- a supported WebRTC transport adapter;
- NVIDIA/CUDA-capable inference runtime;
- hardware video encode/decode where available;
- explicitly selected and licensed face/voice transformation models;
- regional TURN configuration;
- health/readiness endpoints tied to these runtime checks.

This prevents an interface-only build from being reported as a functioning
GPU/WebRTC deployment.
