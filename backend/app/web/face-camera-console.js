(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else {
    root.SeldruneCameraConsole = api;
    if (root.document.getElementById('live-studio')) api.mount(root);
  }
})(typeof window === 'undefined' ? globalThis : window, function () {
  'use strict';

  function usableTrack(track) {
    return !!track && track.kind === 'video' && track.readyState === 'live' &&
      track.enabled !== false && !track.muted;
  }

  function sameSource(left, right) {
    return !!left && !!right && left.video === right.video &&
      left.stream === right.stream && left.track === right.track;
  }

  // Only the existing studio's transformed return is eligible. Never capture
  // the page, use a file URL, or fall back to its unmodified local camera.
  function selectSource(doc) {
    if (!doc) return null;
    const card = doc.querySelector('.output-card.active');
    const video = doc.getElementById('remote-video');
    const local = doc.getElementById('local-video');
    if (!card || !video || !card.contains(video) || video.id !== 'remote-video') return null;
    const stream = video.srcObject;
    if (!stream || stream.active === false || typeof stream.getVideoTracks !== 'function') return null;
    const tracks = stream.getVideoTracks();
    if (tracks.length !== 1 || !usableTrack(tracks[0])) return null;
    const localStream = local && local.srcObject;
    if (stream === localStream) return null;
    if (localStream && typeof localStream.getVideoTracks === 'function' &&
        localStream.getVideoTracks().some(track => track === tracks[0] ||
          (track.id && track.id === tracks[0].id))) return null;
    return {video, stream, track: tracks[0]};
  }

  function createGate(options) {
    const clock = options.clock || (() => performance.now());
    const staleMs = Math.min(options.staleMs || 2000, 2000);
    let source = null;
    let generation = 0;
    let ready = false;
    let disposed = false;
    let lastFrameAt = null;
    let baseline = null;
    let measuredFps = null;
    let lastPresented = null;
    let geometry = '';
    function clear() {
      ready = false;
      lastFrameAt = null;
      baseline = null;
      measuredFps = null;
      lastPresented = null;
      geometry = '';
      options.onClear();
    }
    return {
      observe(next) {
        if (disposed) return generation;
        if (source !== next && !sameSource(source, next)) {
          generation += 1;
          clear();
          source = next;
        }
        return generation;
      },
      frame(observed, ticket, metadata) {
        if (disposed || ticket !== generation || !sameSource(source, observed) ||
            !usableTrack(source.track) || source.stream.active === false) return false;
        const width = Number(metadata.width);
        const height = Number(metadata.height);
        const presented = Number(metadata.presentedFrames);
        if (!Number.isInteger(width) || width < 1 || !Number.isInteger(height) || height < 1 ||
            !Number.isFinite(presented) || presented < 1 ||
            (lastPresented !== null && presented <= lastPresented)) return false;
        const now = clock();
        lastFrameAt = now;
        lastPresented = presented;
        const nextGeometry = width + 'x' + height;
        if (geometry !== nextGeometry) {
          baseline = null;
          measuredFps = null;
        }
        geometry = nextGeometry;
        if (baseline && now - baseline.time >= 1000) {
          measuredFps = Math.max(0, (presented - baseline.frames) * 1000 / (now - baseline.time));
          baseline = {time: now, frames: presented};
        } else if (!baseline) baseline = {time: now, frames: presented};
        if (!ready) {
          ready = true;
          options.onReady(source);
        }
        options.onMetrics({width, height, fps: measuredFps});
        return true;
      },
      tick() {
        if (!source || disposed) return;
        if (!usableTrack(source.track) || source.stream.active === false ||
            (lastFrameAt !== null && clock() - lastFrameAt >= staleMs)) {
          generation += 1;
          source = null;
          clear();
        }
      },
      invalidate() {
        generation += 1;
        source = null;
        clear();
      },
      dispose() {
        this.invalidate();
        disposed = true;
      },
      get ready() { return ready; },
      get generation() { return generation; },
    };
  }

  function watchFrames(video, callback, host) {
    let stopped = false;
    let handle = null;
    if (typeof video.requestVideoFrameCallback === 'function') {
      const receive = (_time, metadata) => {
        if (stopped) return;
        callback({width: metadata.width || video.videoWidth,
          height: metadata.height || video.videoHeight, presentedFrames: metadata.presentedFrames});
        if (!stopped) handle = video.requestVideoFrameCallback(receive);
      };
      handle = video.requestVideoFrameCallback(receive);
      return () => {
        stopped = true;
        if (typeof video.cancelVideoFrameCallback === 'function') video.cancelVideoFrameCallback(handle);
      };
    }
    const count = () => {
      if (typeof video.getVideoPlaybackQuality === 'function') return video.getVideoPlaybackQuality().totalVideoFrames;
      return video.webkitDecodedFrameCount;
    };
    let previous = count();
    handle = host.setInterval(() => {
      const current = count();
      if (!stopped && Number.isFinite(current) && Number.isFinite(previous) && current > previous) {
        callback({width: video.videoWidth, height: video.videoHeight, presentedFrames: current});
      }
      previous = current;
    }, 100);
    return () => { stopped = true; host.clearInterval(handle); };
  }

  function mount(host) {
    const doc = host.document;
    const studio = doc.getElementById('live-studio');
    const preview = doc.getElementById('camera-output');
    const fullscreenButton = doc.getElementById('fullscreen-output');
    const cameraStage = doc.getElementById('camera-stage');
    if (!studio || !preview) return null;
    let source = null;
    let unwatch = () => {};
    let projection = null;
    let popup = null;
    let popupStream = null;
    let measuredGeometry = '';
    let disposed = false;
    let stopped = false;
    let unbindStudio = () => {};
    const setText = (id, value) => {
      const element = doc.getElementById(id);
      if (element) element.textContent = value;
    };
    function popupApi() {
      try {
        if (!popup || popup.closed || popup.location.origin !== host.location.origin) return null;
        return popup.SeldruneCameraOutput || null;
      } catch (_error) { return null; }
    }
    function clearProjection() {
      const api = popupApi();
      if (api) api.detach();
      popupStream = null;
      preview.hidden = true;
      preview.srcObject = null;
      if (projection) projection.getTracks().forEach(track => track.stop());
      projection = null;
      measuredGeometry = '';
      if (fullscreenButton) fullscreenButton.disabled = true;
      setText('feed-state', 'WAITING FOR TRANSFORMED VIDEO');
      setText('measured-resolution', '—');
      setText('measured-fps', '—');
    }
    const gate = createGate({
      clock: () => host.performance.now(), onClear: clearProjection,
      onReady(observed) {
        if (disposed || stopped || !sameSource(observed, readSource())) return;
        projection = new host.MediaStream([observed.track.clone()]);
        preview.srcObject = projection;
        preview.hidden = false;
        if (fullscreenButton) fullscreenButton.disabled = false;
        const play = preview.play();
        if (play && typeof play.catch === 'function') play.catch(() => {});
        setText('feed-state', 'TRANSFORMED PREVIEW');
        setText('console-status', 'Transformed preview is available. Open camera output for OBS Window Capture.');
      },
      onMetrics(metrics) {
        const geometry = metrics.width + ' × ' + metrics.height;
        if (geometry !== measuredGeometry) setText('measured-fps', 'Measuring…');
        measuredGeometry = geometry;
        setText('measured-resolution', geometry);
        if (metrics.fps !== null) setText('measured-fps', metrics.fps.toFixed(1) + ' decoded fps');
      },
    });
    function studioDocument() {
      try {
        const location = studio.contentWindow.location;
        if (location.origin !== host.location.origin ||
            !['/media', '/liveshell/mobile'].includes(location.pathname)) return null;
        return studio.contentDocument;
      } catch (_error) { return null; }
    }
    function readSource() { return selectSource(studioDocument()); }
    function detachSource() {
      unwatch();
      unwatch = () => {};
      source = null;
    }
    function sync() {
      if (disposed) return;
      let next = readSource();
      if (stopped) next = null;
      if (source !== next && !sameSource(source, next)) {
        detachSource();
        const ticket = gate.observe(next);
        source = next;
        if (next) {
          const invalid = () => { gate.invalidate(); detachSource(); };
          next.track.addEventListener('mute', invalid);
          next.track.addEventListener('ended', invalid);
          const stopFrames = watchFrames(next.video, metadata => {
            if (!sameSource(next, readSource())) { invalid(); return; }
            gate.frame(next, ticket, metadata);
          }, host);
          unwatch = () => {
            stopFrames();
            next.track.removeEventListener('mute', invalid);
            next.track.removeEventListener('ended', invalid);
          };
        }
      }
      const before = gate.generation;
      gate.tick();
      if (before !== gate.generation) detachSource();
      const api = popupApi();
      if (projection && api && popupStream !== projection) {
        api.attach(projection);
        popupStream = projection;
      }
    }
    function reset() {
      detachSource();
      gate.invalidate();
      unbindStudio();
      unbindStudio = () => {};
      try {
        const current = studioDocument();
        const form = current && current.getElementById('session-form');
        const resume = () => { stopped = false; };
        if (form) {
          form.addEventListener('submit', resume);
          unbindStudio = () => form.removeEventListener('submit', resume);
        }
      } catch (_error) { /* A cross-origin studio is not an eligible source. */ }
    }
    function openOutput() {
      popup = host.open('/camera/output', 'seldrune-camera-output', 'popup,width=960,height=600');
      popupStream = null;
      if (!popup) setText('console-status', 'Allow the camera output window in this browser, then try again.');
      sync();
    }
    function stopOutput() {
      stopped = true;
      detachSource();
      gate.invalidate();
      try {
        const current = studioDocument();
        const button = current && current.getElementById('stop-button');
        if (button) button.click();
      } catch (_error) { /* A navigated studio has no session we can control. */ }
      setText('console-status', 'Output cleared and the studio session stop was requested.');
    }
    function fullscreenOutput() {
      if (!gate.ready || !projection) {
        setText('console-status', 'Wait for decoded transformed video before opening fullscreen output.');
        return;
      }
      if (!cameraStage || typeof cameraStage.requestFullscreen !== 'function') {
        setText('console-status', 'Fullscreen output is unavailable in this browser. Keep the transformed preview open.');
        return;
      }
      try {
        const request = cameraStage.requestFullscreen();
        if (request && typeof request.catch === 'function') request.catch(() => {
          setText('console-status', 'Fullscreen output was not opened. Keep the transformed preview open.');
        });
      } catch (_error) {
        setText('console-status', 'Fullscreen output was not opened. Keep the transformed preview open.');
      }
    }
    function dispose() {
      if (disposed) return;
      // The studio handler stops local capture synchronously and requests its
      // authenticated remote cleanup; page teardown cannot await that request.
      stopOutput();
      disposed = true;
      host.clearInterval(timer);
      unbindStudio();
      detachSource();
      gate.dispose();
      studio.removeEventListener('load', reset);
      doc.getElementById('open-output').removeEventListener('click', openOutput);
      doc.getElementById('stop-output').removeEventListener('click', stopOutput);
      if (fullscreenButton) fullscreenButton.removeEventListener('click', fullscreenOutput);
      host.removeEventListener('pagehide', dispose);
    }
    preview.hidden = true;
    studio.addEventListener('load', reset);
    doc.getElementById('open-output').addEventListener('click', openOutput);
    doc.getElementById('stop-output').addEventListener('click', stopOutput);
    if (fullscreenButton) fullscreenButton.addEventListener('click', fullscreenOutput);
    host.addEventListener('pagehide', dispose);
    const timer = host.setInterval(sync, 200);
    reset();
    sync();
    return {sync, stop: stopOutput, dispose};
  }

  return {usableTrack, sameSource, selectSource, createGate, watchFrames, mount};
});
