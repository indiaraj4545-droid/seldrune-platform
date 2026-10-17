(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory;
  else factory(root, root.SeldruneCameraConsole);
})(typeof window === 'undefined' ? globalThis : window, function (host, shared) {
  'use strict';
  const video = host.document.getElementById('camera-output');
  const status = host.document.getElementById('output-status');
  const disclosure = host.document.getElementById('output-disclosure');
  if (!video || !status || !disclosure || !shared) return null;
  let stream = null;
  let unwatch = () => {};
  let disposed = false;
  function blank() {
    video.hidden = true;
    status.hidden = false;
    status.textContent = 'Waiting for transformed video';
  }
  const gate = shared.createGate({
    clock: () => host.performance.now(), onClear: blank,
    onReady() { video.hidden = false; status.hidden = true; },
    onMetrics() {},
  });
  function detach() {
    unwatch();
    unwatch = () => {};
    gate.invalidate();
    video.srcObject = null;
    if (stream) stream.getTracks().forEach(track => track.stop());
    stream = null;
    blank();
  }
  function attach(incoming) {
    detach();
    if (disposed || !incoming || typeof incoming.getVideoTracks !== 'function') return false;
    const tracks = incoming.getVideoTracks();
    if (tracks.length !== 1 || !shared.usableTrack(tracks[0])) return false;
    stream = new host.MediaStream([tracks[0].clone()]);
    const track = stream.getVideoTracks()[0];
    video.srcObject = stream;
    const source = {video, stream, track};
    const ticket = gate.observe(source);
    const invalid = () => detach();
    track.addEventListener('mute', invalid);
    track.addEventListener('ended', invalid);
    const stopFrames = shared.watchFrames(video, metadata => gate.frame(source, ticket, metadata), host);
    unwatch = () => {
      stopFrames();
      track.removeEventListener('mute', invalid);
      track.removeEventListener('ended', invalid);
    };
    const play = video.play();
    if (play && typeof play.catch === 'function') play.catch(() => {});
    return true;
  }
  function dispose() {
    disposed = true;
    host.clearInterval(timer);
    detach();
    gate.dispose();
    host.removeEventListener('pagehide', dispose);
  }
  disclosure.textContent = 'AI MODIFIED';
  disclosure.hidden = false;
  video.muted = true;
  blank();
  const timer = host.setInterval(() => {
    let parentAlive = false;
    try { parentAlive = !!host.opener && !host.opener.closed && host.opener.location.origin === host.location.origin; }
    catch (_error) { /* A navigated parent is no longer an authorized source. */ }
    if (!parentAlive) detach();
    else gate.tick();
  }, 200);
  host.addEventListener('pagehide', dispose);
  const api = Object.freeze({attach, detach});
  host.SeldruneCameraOutput = api;
  return {attach, detach, dispose};
});
