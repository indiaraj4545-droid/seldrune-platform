# RunPod RTX 4090 mobile FaceSwap jobs

## Product path

The Seldrune mobile FaceSwap studio is served at `/liveshell/faceswap/mobile` and uses authenticated HTTPS jobs: upload one authorized face image and one target video, poll for completion, then download the result. Once the worker endpoint and matching server token are configured, Seldrune sends each authorized job to RunPod automatically. RunPod Pods do not accept UDP, so this path is separate from the LiveShell WebRTC camera prototype.

The first worker profile uses FaceFusion's `ghost_1_256` face-swap model. FaceFusion's model metadata identifies that model as Apache-2.0; the FaceFusion application source has its own OpenRAIL-AS license. Check both licenses before using the worker outside a permitted context.

The worker preserves the target video's audio and re-encodes it as AAC at 48 kHz. It does not perform voice conversion. The final video has a burned-in `AI-SYNTHETIC` label. Inputs are limited to 30 seconds, 1080p, 75 MB video, and a 15 MB face image. Job files expire after one hour, and the signed-in user can delete them sooner.

## Worker image

Build the worker image from the repository root:

```sh
docker build -f services/live_media/Dockerfile.runpod -t seldrune-faceswap-worker:runpod .
```

The image pins the FaceFusion source revision used for the local integration and installs CUDA-enabled ONNX Runtime. FaceFusion downloads the selected model artifacts from its configured upstream provider when the first job runs.

The `.github/workflows/runpod-worker-image.yml` workflow publishes a private GitHub Container Registry image from changes to the worker or Dockerfile. It tags the image as `ghcr.io/seldrune-platform/seldrune-faceswap-worker:latest` and with the source commit SHA. Because the Seldrune repository is private, RunPod needs a private registry credential with package-read access to pull it. Keep that credential in RunPod's registry-auth settings; do not put it in the workflow or Seldrune's browser client.

Configure the Pod to run this image, set a random `SELDRUNE_FACESWAP_WORKER_TOKEN` environment value, and expose internal port `8000` as HTTP. The Pod proxy is internet-accessible, so keep the bearer token enabled and store its matching value only in the Seldrune server environment. Never place it in browser JavaScript.

The reusable port-update payload is
[`deploy/live-media/runpod-faceswap-ports.json`](../../deploy/live-media/runpod-faceswap-ports.json):

```json
{"ports": ["8000/http", "22/tcp"]}
```

Apply this payload with `PATCH https://rest.runpod.io/v1/pods/{pod_id}` to the
intended stopped worker pod. The port list replaces the pod's exposed ports;
retain any additional ports required by other services when adapting it. For the
FaceSwap validation pod, replace `8888/http` with `8000/http` and preserve
`22/tcp`. Updating ports does not require starting or creating a pod. Port 8888
is not the FaceSwap listener: this image starts Uvicorn on `0.0.0.0:8000`.

The worker base URL is `https://{pod_id}-8000.proxy.runpod.net`. After a separately
authorized start, check `GET /health` and require JSON `status: ready` before
submitting an authenticated multipart request to `POST /v1/jobs`. An HTTP 200
health response alone does not establish GPU readiness. A 502 on port 8888 does
not diagnose the worker listening on port 8000.

## Seldrune settings

Set these server-side values on the Seldrune web service:

- `SELDRUNE_FACESWAP_WORKER_URL`: the RunPod HTTPS proxy URL for port 8000.
- `SELDRUNE_FACESWAP_WORKER_TOKEN`: the same random worker token configured on the Pod.

Seldrune sends organization and user IDs to the worker so it can bind each job to the requesting owner. Requests also require organization run permission, a face-use authorization checkbox, video editing rights confirmation, and the persistent synthetic-media label.

## RunPod lifecycle

The existing RTX 4090 Pod is stopped and uses a generic PyTorch image. It must be updated to run this worker image and expose authenticated HTTPS port `8000` before the app can submit jobs. The Pod costs about `$0.74/hour` while running in the current account. The first integration uses the configured worker endpoint; automatic Pod start/stop is not enabled because it requires a separate RunPod API credential and idle-job lifecycle. Do not expose that API key or worker token to browser clients.

## Evidence

The UI reports actual output dimensions, frame rate, audio sample rate, and the GPU name reported by `nvidia-smi`. 1080p throughput and visual quality remain unverified until tested with an authorized phone video on the 4090.
