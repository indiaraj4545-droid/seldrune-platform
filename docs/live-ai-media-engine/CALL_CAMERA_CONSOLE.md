# Seldrune Call Camera

The separate console is served at `/camera` on the Seldrune origin. It reuses the
authenticated `/media` studio in a same-origin frame. It creates no extra GPU
session and does not record media. Its clean projection is `/camera/output`.

## Supported calling path

1. On the desktop that runs the call, sign in to Seldrune and open `/camera`.
2. In the embedded studio, select authorized profiles, confirm consent and the
   visible AI-modified indicator, and start the live session. The **existing live
   gateway requires both an approved face profile and an approved voice profile**
   and camera/microphone permission. This console does not remove those checks
   or invent a voice profile. If the gateway is unavailable, no live feed appears.
3. Wait for decoded video to appear in the transformed-return panel. Its displayed
   resolution and preview FPS are browser measurements, not an HD, inference
   throughput, end-to-end latency, or conference output guarantee.
4. Install OBS Studio on that desktop, including its virtual-camera support.
   On Linux, an appropriately configured v4l2loopback device is also needed;
   on macOS, allow the OBS camera extension if the OS requests it.
5. Select **Open clean output**. Keep this browser window visible and unminimized.
   In OBS, add a **Window Capture** of **Seldrune Camera Output**, fit it to a
   1920×1080 canvas, and start **Virtual Camera**. Use Window Capture of the
   already authenticated output, rather than putting an authenticated URL or
   credentials into an OBS Browser Source. OBS's canvas resolution does not
   establish that source video was transformed at 1080p.
6. Choose **OBS Virtual Camera** in your meeting app:
   - Zoom: Settings → Video → Camera.
   - Teams: Settings → Devices → Camera (or the call's device settings).
   - Google Meet on desktop: Settings → Video → Camera.
7. Keep your normal microphone selected in the meeting app. The projection is
   muted video only; it does not route Seldrune audio into that app.
8. Use **Stop live session** to stop capture and release the existing gateway
   session. Stop OBS Virtual Camera when finished with calls.

Camera availability also depends on the meeting app's policy and OS permissions.
This is a supported virtual-camera workflow, not injection into third-party apps.
The console cannot install OBS or approve camera permissions on a remote computer.

## Mobile boundary

Android/iOS browsers can preview the Seldrune return. **Fullscreen output** keeps
the returned video in the active console tab on browsers that support element
fullscreen. It starts no additional capture or session. If the meeting app and
phone support screen sharing, the user can share that browser view as content;
it is not a camera input, and sustained mobile capture still needs device testing.
Normal mobile apps cannot
register a browser stream as the system camera for unrelated native Zoom, Teams,
or Meet apps. Use mobile preview/screen sharing, or a desktop virtual-camera
companion. This console does not claim universal mobile-camera substitution.

## Output safety and lifecycle

Only the embedded studio's **remote returned video** can be projected. The local
camera is never a projection fallback. A stream is withheld until an actual
decoded frame is observed, and blanked on mute, ended track, detached stream,
source reload, or stale frames. A permanently visible AI MODIFIED overlay is kept
on the output window in addition to the gateway's embedded disclosure.

The console passes an in-memory, same-origin video stream to its projection
window. It sends no bearer tokens or session identifiers to the window, writes no
media to storage, and makes no extra worker job submission. Camera/microphone and
display capture are denied by the output page's Permissions Policy. Closing the
console clears its projection and requests the embedded studio's stop action.
Browser unload cannot await an asynchronous remote close; the existing live
gateway also releases disconnected sessions through its disconnect timeout.

## Required live infrastructure

The uploaded-video `/v1/jobs` worker on HTTP 8000 does **not** provide this live
camera. It needs the separate live GPU worker, authenticated TLS transport,
WebRTC gateway, TURN, private profile media and reviewed grants described in
[the live worker deployment guide](RUNPOD_LIVE_WORKER_DEPLOYMENT.md).
Configuration status alone does not prove a successful transformed stream.

No new RunPod resources, image change, deployment, or secret update is necessary
to implement the console UI. Deploy the reviewed web/API change through the
existing Seldrune release process, then perform a genuine desktop call to prove
OBS camera selection, visible output and acceptable performance.

## Local checks

From the repository root, using the existing development environment:

```sh
python -m pytest -q tests/test_face_camera_console.py tests/test_liveshell_mobile_gateway.py tests/test_seldrune_media_client.py
node --test tests/js/test_face_camera_console.cjs
python -m ruff check backend/app/api/routes/liveshell_mobile.py tests/test_face_camera_console.py
git diff --check
```

These checks verify console delivery, authorization boundaries and projection
lifecycle. Actual cloud transformation, OS camera delivery and meeting-app
compatibility require a configured worker and a real desktop/device test.
