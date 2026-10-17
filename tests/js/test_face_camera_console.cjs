'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const shared = require('../../backend/app/web/face-camera-console.js');
const mountOutput = require('../../backend/app/web/face-camera-output.js');

class Events {
  constructor() { this.handlers = new Map(); }
  addEventListener(name, callback) {
    if (!this.handlers.has(name)) this.handlers.set(name, new Set());
    this.handlers.get(name).add(callback);
  }
  removeEventListener(name, callback) { this.handlers.get(name)?.delete(callback); }
  emit(name) { for (const callback of [...(this.handlers.get(name) || [])]) callback(); }
  click() { this.emit('click'); }
}

class Track extends Events {
  constructor() { super(); this.kind = 'video'; this.readyState = 'live'; this.enabled = true; this.muted = false; this.clones = []; }
  clone() { const clone = new Track(); this.clones.push(clone); return clone; }
  stop() { this.readyState = 'ended'; this.emit('ended'); }
}

class Stream {
  constructor(tracks) { this.tracks = tracks; this.active = true; }
  getVideoTracks() { return this.tracks.filter(track => track.kind === 'video'); }
  getTracks() { return this.tracks; }
}

class Video extends Events {
  constructor(id) { super(); this.id = id; this.srcObject = null; this.hidden = false; this.callbacks = new Map(); this.next = 0; }
  play() { return Promise.resolve(); }
  requestVideoFrameCallback(callback) { const handle = ++this.next; this.callbacks.set(handle, callback); return handle; }
  cancelVideoFrameCallback(handle) { this.callbacks.delete(handle); }
  frame(frames = 1, width = 1920, height = 1080) {
    this.videoWidth = width;
    this.videoHeight = height;
    const [handle, callback] = this.callbacks.entries().next().value || [];
    if (callback) { this.callbacks.delete(handle); callback(0, {width, height, presentedFrames: frames}); }
  }
}

function fixture() {
  const remote = new Video('remote-video');
  const local = new Video('local-video');
  const track = new Track();
  remote.srcObject = new Stream([track]);
  local.srcObject = new Stream([new Track()]);
  const card = {contains: video => video === remote};
  const elements = new Map([['remote-video', remote], ['local-video', local], ['stop-button', new Events()], ['session-form', new Events()]]);
  const doc = {
    active: true,
    querySelector: selector => selector === '.output-card.active' && doc.active ? card : null,
    getElementById: id => elements.get(id) || null,
  };
  return {doc, track, remote, local, elements};
}

function hostFor(elements) {
  const host = new Events();
  host.document = {getElementById: id => elements.get(id) || null};
  host.now = 0;
  host.performance = {now: () => host.now};
  host.location = {origin: 'https://camera.example'};
  host.MediaStream = Stream;
  host.intervals = new Map();
  let next = 0;
  host.setInterval = callback => { host.intervals.set(++next, callback); return next; };
  host.clearInterval = handle => host.intervals.delete(handle);
  host.tick = () => { for (const callback of [...host.intervals.values()]) callback(); };
  return host;
}

function consoleFixture() {
  const input = fixture();
  const studio = new Events();
  studio.contentDocument = input.doc;
  studio.contentWindow = {location: {origin: 'https://camera.example', pathname: '/media'}};
  const elements = new Map([['live-studio', studio], ['camera-output', new Video('camera-output')]]);
  for (const id of ['feed-state', 'measured-resolution', 'measured-fps', 'open-output', 'stop-output', 'console-status']) elements.set(id, new Events());
  const host = hostFor(elements);
  const calls = [];
  const popup = {closed: false, location: host.location,
    SeldruneCameraOutput: {attach: stream => calls.push(['attach', stream]), detach: () => calls.push(['detach'])}};
  host.open = (...args) => { calls.push(['open', ...args]); return popup; };
  return {...input, host, studio, elements, popup, calls};
}

test('source selection accepts only active transformed return, never local or file media', () => {
  const input = fixture();
  assert.equal(shared.selectSource(input.doc).track, input.track);
  input.doc.active = false;
  assert.equal(shared.selectSource(input.doc), null);
  input.doc.active = true;
  input.remote.id = 'local-video';
  assert.equal(shared.selectSource(input.doc), null);
  input.remote.id = 'remote-video';
  input.remote.srcObject = input.local.srcObject;
  assert.equal(shared.selectSource(input.doc), null);
  input.remote.srcObject = null;
  input.remote.src = 'file:///unmodified-video';
  assert.equal(shared.selectSource(input.doc), null);
});

test('source selection rejects shared local tracks, inactive streams, muted and ended video', () => {
  const input = fixture();
  input.local.srcObject = new Stream([input.track]);
  assert.equal(shared.selectSource(input.doc), null);
  input.local.srcObject = null;
  for (const property of ['muted', 'enabled', 'readyState']) {
    const previous = input.track[property];
    input.track[property] = {muted: true, enabled: false, readyState: 'ended'}[property];
    assert.equal(shared.selectSource(input.doc), null);
    input.track[property] = previous;
  }
  input.remote.srcObject.active = false;
  assert.equal(shared.selectSource(input.doc), null);
});

test('gate requires a decoded frame, measures preview FPS, and rejects duplicate frames', () => {
  const input = fixture();
  const source = shared.selectSource(input.doc);
  let now = 0;
  let ready = 0;
  const metrics = [];
  const gate = shared.createGate({clock: () => now, onReady: () => ready++, onClear() {}, onMetrics: value => metrics.push(value)});
  const ticket = gate.observe(source);
  assert.equal(gate.ready, false);
  assert.equal(gate.frame(source, ticket, {width: 0, height: 1080, presentedFrames: 1}), false);
  gate.frame(source, ticket, {width: 1920, height: 1080, presentedFrames: 1});
  assert.equal(ready, 1);
  assert.equal(metrics[0].fps, null);
  now = 1000;
  gate.frame(source, ticket, {width: 1920, height: 1080, presentedFrames: 31});
  assert.equal(metrics[1].fps, 30);
  assert.equal(gate.frame(source, ticket, {width: 1920, height: 1080, presentedFrames: 31}), false);
});

test('preview FPS keeps its last sample between windows and resets with geometry', () => {
  const input = fixture();
  const source = shared.selectSource(input.doc);
  let now = 0;
  const metrics = [];
  const gate = shared.createGate({clock: () => now, onReady() {}, onClear() {}, onMetrics: value => metrics.push(value)});
  const ticket = gate.observe(source);
  const frame = (frames, width = 1920, height = 1080) => gate.frame(source, ticket, {width, height, presentedFrames: frames});
  frame(1);
  now = 1000;
  frame(31);
  assert.equal(metrics.at(-1).fps, 30);
  now = 1500;
  frame(46);
  assert.equal(metrics.at(-1).fps, 30);
  now = 1600;
  frame(49, 1280, 720);
  assert.equal(metrics.at(-1).fps, null);
  now = 2600;
  frame(73, 1280, 720);
  assert.equal(metrics.at(-1).fps, 24);
});

test('idle null observations never repeatedly invalidate or clear the projection gate', () => {
  let clears = 0;
  const gate = shared.createGate({onReady() {}, onClear: () => clears++, onMetrics() {}});
  gate.observe(null);
  gate.observe(null);
  gate.tick();
  assert.equal(gate.generation, 0);
  assert.equal(clears, 0);
});

test('gate invalidates mute, end, timeout, source change and late callbacks after stop/dispose', () => {
  for (const reason of ['mute', 'end', 'timeout', 'change', 'stop', 'dispose']) {
    const input = fixture();
    const source = shared.selectSource(input.doc);
    let now = 0;
    let clears = 0;
    const gate = shared.createGate({clock: () => now, onReady() {}, onClear: () => clears++, onMetrics() {}});
    const ticket = gate.observe(source);
    const frame = {width: 1920, height: 1080, presentedFrames: 1};
    gate.frame(source, ticket, frame);
    if (reason === 'mute') input.track.muted = true;
    if (reason === 'end') input.track.readyState = 'ended';
    if (reason === 'timeout') now = 2000;
    if (reason === 'change') gate.observe({...source, stream: new Stream([input.track])});
    if (reason === 'stop') gate.invalidate();
    if (reason === 'dispose') gate.dispose();
    gate.tick();
    assert.equal(gate.ready, false, reason);
    assert.equal(gate.frame(source, ticket, {...frame, presentedFrames: 2}), false, reason);
    assert.ok(clears >= 2, reason);
  }
});

test('fallback requires an increment in a real decoded-frame counter', () => {
  const host = hostFor(new Map());
  const video = {videoWidth: 1280, videoHeight: 720, getVideoPlaybackQuality: () => ({totalVideoFrames: count})};
  let count = 20;
  const frames = [];
  const stop = shared.watchFrames(video, frame => frames.push(frame), host);
  host.tick();
  assert.equal(frames.length, 0);
  count = 21;
  host.tick();
  assert.deepEqual(frames, [{width: 1280, height: 720, presentedFrames: 21}]);
  stop();
  assert.equal(host.intervals.size, 0);
});

test('dimensions or advancing media time alone never unlock an unsupported frame observer', () => {
  const host = hostFor(new Map());
  const video = {videoWidth: 1920, videoHeight: 1080, currentTime: 2};
  let frames = 0;
  const stop = shared.watchFrames(video, () => frames++, host);
  host.tick();
  video.currentTime = 3;
  host.tick();
  assert.equal(frames, 0);
  stop();
});

test('console projects only video clones and opens a same-origin output window', () => {
  const input = consoleFixture();
  const mounted = shared.mount(input.host);
  const preview = input.elements.get('camera-output');
  assert.equal(preview.hidden, true);
  assert.equal(input.track.clones.length, 0);
  input.remote.frame();
  assert.equal(preview.hidden, false);
  assert.equal(preview.srcObject.getTracks().length, 1);
  assert.equal(preview.srcObject.getTracks()[0], input.track.clones[0]);
  input.elements.get('open-output').click();
  assert.equal(input.calls.find(call => call[0] === 'open')[1], '/camera/output');
  assert.equal(input.calls.filter(call => call[0] === 'attach').length, 1);
  mounted.dispose();
  assert.equal(input.track.readyState, 'live');
  assert.equal(preview.hidden, true);
  assert.equal(preview.srcObject, null);
  assert.equal(input.track.clones[0].readyState, 'ended');
  assert.equal(input.host.intervals.size, 0);
  assert.equal(input.calls.at(-1)[0], 'detach');
});

test('stop invalidates inflight callbacks and blocks a late stream until explicit studio restart', () => {
  const input = consoleFixture();
  const mounted = shared.mount(input.host);
  const pending = [...input.remote.callbacks.values()][0];
  let stopRequested = 0;
  input.doc.getElementById('stop-button').addEventListener('click', () => stopRequested++);
  input.elements.get('stop-output').click();
  pending(0, {width: 1920, height: 1080, presentedFrames: 1});
  const newTrack = new Track();
  input.remote.srcObject = new Stream([newTrack]);
  mounted.sync();
  input.remote.frame();
  assert.equal(newTrack.clones.length, 0);
  assert.equal(input.elements.get('camera-output').srcObject, null);
  assert.equal(stopRequested, 1);
  input.doc.getElementById('session-form').emit('submit');
  mounted.sync();
  input.remote.frame(2);
  assert.equal(newTrack.clones.length, 1);
  mounted.dispose();
});

test('source replacement blanks old media and requires a new decoded frame', () => {
  const input = consoleFixture();
  const mounted = shared.mount(input.host);
  input.remote.frame();
  const previousClone = input.track.clones[0];
  const newTrack = new Track();
  input.remote.srcObject = new Stream([newTrack]);
  mounted.sync();
  assert.equal(previousClone.readyState, 'ended');
  assert.equal(input.elements.get('camera-output').hidden, true);
  assert.equal(newTrack.clones.length, 0);
  input.remote.frame(2, 1280, 720);
  assert.equal(input.elements.get('measured-resolution').textContent, '1280 × 720');
  assert.equal(input.elements.get('measured-fps').textContent, 'Measuring…');
  assert.equal(newTrack.clones.length, 1);
  mounted.dispose();
});

test('iframe reload, source mute and page teardown clear projection and popup', () => {
  for (const action of ['reload', 'mute', 'timeout', 'pagehide']) {
    const input = consoleFixture();
    const mounted = shared.mount(input.host);
    input.remote.frame();
    input.elements.get('open-output').click();
    if (action === 'reload') input.studio.emit('load');
    if (action === 'mute') { input.track.muted = true; input.track.emit('mute'); }
    if (action === 'timeout') { input.host.now = 2000; mounted.sync(); }
    if (action === 'pagehide') input.host.emit('pagehide');
    assert.equal(input.elements.get('camera-output').srcObject, null, action);
    assert.equal(input.calls.at(-1)[0], 'detach', action);
    assert.equal(input.track.readyState, 'live', action);
    if (action !== 'pagehide') mounted.dispose();
  }
});

test('console accepts only the two known same-origin studio paths', () => {
  for (const pathname of ['/media', '/liveshell/mobile', '/unrelated', '/media/other']) {
    const input = consoleFixture();
    input.studio.contentWindow.location.pathname = pathname;
    const mounted = shared.mount(input.host);
    input.remote.frame();
    assert.equal(input.elements.get('camera-output').hidden,
      !['/media', '/liveshell/mobile'].includes(pathname), pathname);
    mounted.dispose();
  }
});

test('page teardown requests studio stop once and releases projected tracks', () => {
  const input = consoleFixture();
  let stops = 0;
  input.doc.getElementById('stop-button').addEventListener('click', () => stops++);
  const mounted = shared.mount(input.host);
  input.remote.frame();
  const clone = input.track.clones[0];
  input.host.emit('pagehide');
  mounted.dispose();
  assert.equal(stops, 1);
  assert.equal(clone.readyState, 'ended');
  assert.equal(input.elements.get('camera-output').srcObject, null);
  assert.equal(input.host.intervals.size, 0);
});

test('fullscreen uses only decoded transformed stage and safely handles denial or unsupported browsers', async () => {
  const input = consoleFixture();
  const button = new Events();
  let requests = 0;
  const stage = {requestFullscreen: () => { requests++; return Promise.resolve(); }};
  input.elements.set('fullscreen-output', button);
  input.elements.set('camera-stage', stage);
  const mounted = shared.mount(input.host);
  assert.equal(button.disabled, true);
  button.click();
  assert.equal(requests, 0);
  assert.match(input.elements.get('console-status').textContent, /Wait for decoded transformed video/);
  input.remote.frame();
  assert.equal(button.disabled, false);
  button.click();
  assert.equal(requests, 1);
  stage.requestFullscreen = undefined;
  button.click();
  assert.match(input.elements.get('console-status').textContent, /unavailable in this browser/);
  stage.requestFullscreen = () => Promise.reject(new Error('private browser detail'));
  button.click();
  await Promise.resolve();
  assert.equal(input.elements.get('console-status').textContent,
    'Fullscreen output was not opened. Keep the transformed preview open.');
  stage.requestFullscreen = () => { throw new Error('private browser detail'); };
  button.click();
  assert.doesNotMatch(input.elements.get('console-status').textContent, /private browser detail/);
  mounted.dispose();
  assert.equal(button.disabled, true);
  stage.requestFullscreen = () => requests++;
  button.click();
  assert.equal(requests, 1);
});

test('popup access is refused after cross-origin navigation', () => {
  const input = consoleFixture();
  const mounted = shared.mount(input.host);
  input.remote.frame();
  input.popup.location = {origin: 'https://other.example'};
  input.elements.get('open-output').click();
  assert.equal(input.calls.some(call => call[0] === 'attach'), false);
  mounted.dispose();
});

test('output remains blank before decoding, retains disclosure, and clears if parent closes', () => {
  const elements = new Map([['camera-output', new Video('camera-output')], ['output-status', new Events()], ['output-disclosure', new Events()]]);
  const host = hostFor(elements);
  host.opener = {closed: false, location: host.location};
  const output = mountOutput(host, shared);
  const original = new Track();
  assert.equal(output.attach(new Stream([original])), true);
  const video = elements.get('camera-output');
  assert.equal(video.hidden, true);
  video.frame();
  assert.equal(video.hidden, false);
  assert.equal(elements.get('output-disclosure').textContent, 'AI MODIFIED');
  assert.equal(elements.get('output-disclosure').hidden, false);
  assert.equal(video.muted, true);
  host.opener.closed = true;
  host.tick();
  assert.equal(video.srcObject, null);
  assert.equal(video.hidden, true);
  assert.equal(original.readyState, 'live');
  assert.equal(original.clones[0].readyState, 'ended');
  output.dispose();
  assert.equal(host.intervals.size, 0);
});

test('output rejects invalid media and ignores callbacks after detach', () => {
  const elements = new Map([['camera-output', new Video('camera-output')], ['output-status', new Events()], ['output-disclosure', new Events()]]);
  const host = hostFor(elements);
  host.opener = {closed: false, location: host.location};
  const output = mountOutput(host, shared);
  assert.equal(output.attach({}), false);
  assert.equal(output.attach(new Stream([{kind: 'audio'}])), false);
  output.attach(new Stream([new Track()]));
  const video = elements.get('camera-output');
  const callback = [...video.callbacks.values()][0];
  output.detach();
  callback(0, {width: 1920, height: 1080, presentedFrames: 1});
  assert.equal(video.hidden, true);
  assert.equal(video.srcObject, null);
  output.dispose();
});

test('output hides its retained frame on local decode stall or mute', () => {
  for (const reason of ['stall', 'mute']) {
    const elements = new Map([['camera-output', new Video('camera-output')], ['output-status', new Events()], ['output-disclosure', new Events()]]);
    const host = hostFor(elements);
    host.opener = {closed: false, location: host.location};
    const output = mountOutput(host, shared);
    const original = new Track();
    output.attach(new Stream([original]));
    const video = elements.get('camera-output');
    video.frame();
    assert.equal(video.hidden, false);
    if (reason === 'stall') { host.now = 2000; host.tick(); }
    else { original.clones[0].muted = true; original.clones[0].emit('mute'); }
    assert.equal(video.hidden, true, reason);
    assert.equal(elements.get('output-disclosure').hidden, false, reason);
    output.dispose();
  }
});

test('projection code has no token access, new capture, network requests or cross-window serialization', () => {
  for (const file of ['face-camera-console.js', 'face-camera-output.js']) {
    const source = fs.readFileSync(path.join(__dirname, '../../backend/app/web', file), 'utf8');
    assert.doesNotMatch(source, /sessionStorage|localStorage|Authorization|Bearer|fetch\s*\(|getUserMedia\s*\(|captureStream\s*\(|postMessage\s*\(|JSON\./);
  }
});
