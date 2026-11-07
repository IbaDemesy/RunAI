const test = require("node:test");
const assert = require("node:assert/strict");
const { createVoiceInput, parseJourneyCommand } = require("../voice-input.js");

function setup(options = {}) {
  const states = [], calls = [];
  let stopped = 0, recorder;
  class Recorder {
    constructor() { recorder = this; this.mimeType = "audio/webm"; }
    start() {}
    stop() {
      this.ondataavailable({ data: new Blob(["audio"], { type: this.mimeType }) });
      this.onstop();
    }
  }
  const input = createVoiceInput({
    WebSocket: false,
    getUserMedia: async () => ({ getTracks: () => [{ stop: () => stopped++ }] }),
    MediaRecorder: Recorder,
    fetch: async (url, init) => {
      calls.push([url, init]);
      return { ok: true, json: async () => ({ text: "I want to plan my race trip" }) };
    },
    getRevision: () => 4,
    onStateChange: state => states.push(state.state),
    onFramingReply: body => calls.push(body),
    ...options,
  });
  return { input, states, calls, stopped: () => stopped, recorder: () => recorder };
}

test("recording states and raw transcribe request then framing reply", async () => {
  const { input, states, calls, stopped } = setup();
  assert.equal(input.getState().state, "idle");
  await input.start();
  assert.equal(await input.start(), false);
  input.stop();
  await input.whenSettled();
  assert.deepEqual(states, ["requesting_permission", "listening", "transcribing", "idle"]);
  assert.equal(stopped(), 1);
  assert.equal(calls[0][0], "/api/transcribe");
  assert.equal(calls[0][1].headers["Content-Type"], "audio/webm");
  assert.equal(await calls[0][1].body.text(), "audio");
  assert.deepEqual(calls[1], { revision: 4, text: "I want to plan my race trip", channel: "voice" });
});

test("permission denied and unsupported retain text fallback", async () => {
  const denied = setup({ getUserMedia: async () => { throw Object.assign(new Error("denied"), { name: "NotAllowedError" }); } });
  await denied.input.start();
  assert.equal(denied.input.getState().state, "permission_denied");
  assert.equal(denied.input.getState().textFallback, true);
  assert.equal(denied.input.getState().message, "Microphone permission denied");
  await denied.input.whenSettled();
  const unsupported = setup({ MediaRecorder: false });
  await unsupported.input.start();
  assert.equal(unsupported.input.getState().state, "unsupported");
  assert.equal(unsupported.input.getState().textFallback, true);
});

test("HTTP, empty, malformed and network transcription errors never fabricate text", async () => {
  for (const fetch of [
    async () => ({ ok: false, status: 503, text: async () => "GLADIA_API_KEY missing" }),
    async () => ({ ok: true, json: async () => ({ text: "" }) }),
    async () => ({ ok: true, json: async () => ({}) }),
    async () => { throw new Error("network down"); },
  ]) {
    const { input, calls } = setup({ fetch });
    await input.start(); input.stop(); await input.whenSettled();
    assert.equal(input.getState().state, "error");
    assert.equal(input.getState().textFallback, true);
    assert.ok(input.getState().message);
    assert.deepEqual(calls, []);
  }
});

test("microphone construction and recorder errors release tracks", async () => {
  const broken = setup({ MediaRecorder: class { constructor() { throw new Error("mic broken"); } } });
  await broken.input.start();
  assert.equal(broken.input.getState().state, "error");
  assert.equal(broken.stopped(), 1);
  const recording = setup();
  await recording.input.start();
  recording.recorder().onerror({ error: new Error("recording failed") });
  recording.recorder().onstop();
  assert.equal(recording.input.getState().state, "error");
  assert.equal(recording.stopped(), 1);
});

const cases = [
  ["pause", "agents", "pause"], ["mets en pause les agents", "agents", "pause"],
  ["agents pause", "agents", "pause"], ["PAUSE CAMÉRA!", "camera", "pause"],
  ["arrête la caméra", "camera", "pause"], ["stop the camera", "camera", "pause"],
  ["reprends", "agents", "resume"], ["continue", "agents", "resume"],
  ["resume the agents", "agents", "resume"], ["reprends le survol", "camera", "play"],
  ["reprends la caméra", "camera", "play"], ["play the camera", "camera", "play"],
];
test("FR/EN commands distinguish agents from camera", () => {
  for (const [text, target, action] of cases) assert.deepEqual(parseJourneyCommand(text), { target, action });
  for (const text of ["", "bonjour", "je veux un hôtel", "don't pause", "ne mets pas en pause les agents", "km -1", "km NaN", "je cours 30 km", "pause puis annule"])
    assert.equal(parseJourneyCommand(text), null);
});

test("all actual chapter ids and decimal kilometers", () => {
  const { CHAPTER_IDS } = require("../../flyover/journey-contract.js");
  const phrases = ["voir la maison", "montre la gare", "montre le trajet", "voir l’hôtel", "voir le dossard", "la course", "montre le retour"];
  assert.deepEqual(phrases.map(text => parseJourneyCommand(text).chapter_id), CHAPTER_IDS);
  for (const [text, km] of [["km 30", 30], ["va au kilomètre 21,5", 21.5], ["kilometer 10", 10], ["km 0", 0]])
    assert.deepEqual(parseJourneyCommand(text), { target: "journey", action: "seek_km", seek_km: km });
});

test("dispatch commands to view or agents, never framing", async () => {
  const results = [];
  const view = Object.fromEntries(["pause", "play", "showChapter", "seekKm"].map(method => [method, value => results.push([method, value])]));
  for (const text of ["pause", "reprends", "pause caméra", "reprends le survol", "voir l'hôtel", "km 21,5"]) {
    const { input, calls } = setup({ view, onAgentsCommand: action => results.push(["agents", action]), fetch: async () => ({ ok: true, json: async () => ({ text }) }) });
    await input.start(); input.stop(); await input.whenSettled();
    assert.equal(input.getState().state, "idle");
    assert.deepEqual(calls, []);
  }
  assert.deepEqual(results, [["agents", "pause"], ["agents", "resume"], ["pause", undefined], ["play", undefined], ["showChapter", "arrival_hotel"], ["seekKm", 21.5]]);
});

test("missing wiring and failing callbacks expose honest errors", async () => {
  for (const options of [
    { getRevision: () => undefined },
    { onFramingReply: async () => { throw new Error("409 revision obsolete"); } },
    { fetch: async () => ({ ok: true, json: async () => ({ text: "pause" }) }) },
  ]) {
    const { input } = setup(options);
    await input.start(); input.stop(); await input.whenSettled();
    assert.equal(input.getState().state, "error");
  }
});

const tick = () => new Promise(resolve => setImmediate(resolve));

function streamingSetup(options = {}, { worklet = false, sampleRate = 48000 } = {}) {
  const sockets = [], contexts = [], partials = [], events = [];
  class Socket {
    constructor(url) { this.url = url; this.readyState = 0; this.bufferedAmount = 0; this.sent = []; sockets.push(this); }
    send(data) { assert.equal(this.readyState, 1); this.sent.push(data); }
    close() { this.closed = true; this.readyState = 3; this.onclose?.(); }
    open() { this.readyState = 1; this.onopen(); }
    receive(event) { this.onmessage?.({ data: JSON.stringify(event) }); }
  }
  class Node {
    connect(node) { this.connected = node; }
    disconnect() { this.disconnected = true; }
  }
  class Context {
    constructor() {
      contexts.push(this);
      this.sampleRate = sampleRate;
      this.destination = {};
      if (worklet) this.audioWorklet = { addModule: async url => { this.module = url; } };
    }
    async resume() { this.resumed = true; }
    async close() { this.closed = true; }
    createMediaStreamSource() { return this.source = new Node(); }
    createScriptProcessor(size, inputs, outputs) {
      assert.deepEqual([size, inputs, outputs], [4096, 1, 1]);
      return this.processor = new Node();
    }
    createGain() { const node = new Node(); node.gain = {}; return this.mute = node; }
  }
  class Worklet extends Node {
    constructor(context, name, options) {
      super(); this.port = {};
      assert.equal(name, "runai-pcm");
      assert.equal(options.channelCount, 1);
      context.processor = this;
    }
  }
  const base = setup({
    WebSocket: Socket,
    AudioContext: Context,
    AudioWorkletNode: Worklet,
    location: { protocol: "https:", host: "runai.example:443" },
    onPartial: event => partials.push(event),
    onEvent: event => events.push(event),
    ...options,
  });
  return {
    ...base, sockets, contexts, partials, events,
    socket: () => sockets.at(-1),
    context: () => contexts.at(-1),
    async start() {
      const pending = base.input.start();
      await tick();
      sockets.at(-1).open();
      sockets.at(-1).receive({ type: "ready" });
      assert.equal(await pending, true);
    },
    samples(values) {
      const node = contexts.at(-1).processor;
      if (worklet) node.port.onmessage?.({ data: values });
      else node.onaudioprocess?.({ inputBuffer: { getChannelData: () => values } });
    },
  };
}

test("stream sends start, 100 ms PCM frames, tail, then stop and waits for ended", async () => {
  let constraints;
  const s = streamingSetup({ getUserMedia: async value => {
    constraints = value;
    return { getTracks: () => [] };
  } });
  await s.start();
  assert.deepEqual(constraints, { audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
  assert.equal(s.socket().url, "wss://runai.example:443/api/voice/stream");
  assert.equal(s.socket().binaryType, "arraybuffer");
  assert.deepEqual(JSON.parse(s.socket().sent[0]), { type: "start", sample_rate: 16000 });
  assert.equal(s.context().mute.gain.value, 0);
  assert.equal(s.context().resumed, true);
  s.samples(new Float32Array(4800).fill(0.5));
  s.samples(new Float32Array(3).fill(-1));
  assert.equal(s.socket().sent[1].byteLength, 3200);
  assert.equal(new DataView(s.socket().sent[1]).getInt16(0, true), 16384);
  s.input.stop();
  s.input.stop();
  const sent = s.socket().sent;
  assert.equal(sent[2].byteLength, 2);
  assert.equal(new DataView(sent[2]).getInt16(0, true), -32768);
  assert.deepEqual(JSON.parse(sent[3]), { type: "stop" });
  assert.equal(sent.length, 4);
  assert.equal(s.context().closed, true);
  assert.equal(s.context().source.disconnected, true);
  assert.equal(s.input.getState().state, "transcribing");
  let settled = false;
  s.input.whenSettled().then(() => { settled = true; });
  await tick();
  assert.equal(settled, false);
  s.socket().receive({ type: "transcript", utterance_id: 1, text: "Plan my race trip", language: "en", is_final: true });
  s.socket().receive({ type: "ended" });
  await s.input.whenSettled();
  assert.deepEqual(s.states, ["requesting_permission", "listening", "transcribing", "idle"]);
  assert.equal(s.socket().closed, true);
  assert.deepEqual(s.calls, [{ revision: 4, text: "Plan my race trip", channel: "voice" }]);
});

test("partials replace per utterance, final corrections route once in utterance order", async () => {
  const visible = new Map();
  let revision = 4;
  const s = streamingSetup({ getRevision: () => revision, onPartial: event => visible.set(event.utterance_id, event.text) });
  await s.start();
  revision = 5;
  for (const event of [
    { utterance_id: "a", text: "Plan", is_final: false },
    { utterance_id: "a", text: "Plan my trip", is_final: false },
    { utterance_id: "b", text: "next spring", is_final: true },
    { utterance_id: "a", text: "Plan my race", is_final: true },
    { utterance_id: "a", text: "Plan my race trip", is_final: true },
  ]) s.socket().receive({ type: "transcript", language: "en", ...event });
  assert.equal(visible.get("a"), "Plan my race trip");
  assert.deepEqual(s.calls, []);
  for (const type of ["translation", "entities", "speech"]) s.socket().receive({ type, data: {} });
  s.input.stop();
  s.socket().receive({ type: "ended" });
  s.socket().receive({ type: "ended" });
  await s.input.whenSettled();
  assert.deepEqual(s.calls, [{ revision: 4, text: "Plan my race trip next spring", channel: "voice" }]);
  assert.deepEqual(s.events.map(event => event.type), ["ready", "translation", "entities", "speech", "ended"]);
});

test("every transcript calls onPartial with the server fields", async () => {
  const s = streamingSetup();
  await s.start();
  const values = [
    { utterance_id: 7, text: "A", language: "en", is_final: false },
    { utterance_id: 7, text: "A race", language: "en", is_final: true },
  ];
  values.forEach(value => s.socket().receive({ type: "transcript", ...value }));
  assert.deepEqual(s.partials, values);
  s.input.stop(); s.socket().receive({ type: "ended" }); await s.input.whenSettled();
});

test("resampling has no block-boundary drift at 44.1 and 48 kHz and clips PCM", async () => {
  for (const sampleRate of [44100, 48000]) {
    const s = streamingSetup({}, { sampleRate });
    await s.start();
    let remaining = sampleRate;
    while (remaining) {
      const size = Math.min(remaining, 127);
      s.samples(new Float32Array(size).fill(2));
      remaining -= size;
    }
    assert.equal(s.socket().sent.length, 11);
    const frames = s.socket().sent.slice(1);
    assert.equal(frames.reduce((sum, value) => sum + value.byteLength, 0), 32000);
    for (const frame of frames) for (let i = 0; i < frame.byteLength; i += 2)
      assert.equal(new DataView(frame).getInt16(i, true), 32767);
    s.input.stop(); s.socket().receive({ type: "ended" }); await s.input.whenSettled();
  }
});

test("AudioWorklet receives microphone samples without playing them back", async () => {
  const s = streamingSetup({}, { worklet: true });
  await s.start();
  assert.equal(s.context().module, "/static/voice/pcm-worklet.js");
  s.samples(new Float32Array(4800).fill(-0.5));
  assert.equal(s.socket().sent[1].byteLength, 3200);
  assert.equal(new DataView(s.socket().sent[1]).getInt16(0, true), -16384);
  s.input.stop(); s.socket().receive({ type: "ended" }); await s.input.whenSettled();
});

test("PCM worklet transfers copied mono samples and stays alive for silent input", () => {
  const fs = require("node:fs"), vm = require("node:vm");
  let Processor;
  vm.runInNewContext(fs.readFileSync(require.resolve("../pcm-worklet.js"), "utf8"), {
    AudioWorkletProcessor: class {}, Float32Array,
    registerProcessor(name, value) { assert.equal(name, "runai-pcm"); Processor = value; },
  });
  const processor = new Processor(), posted = [];
  processor.port = { postMessage: (data, transfers) => posted.push({ data, transfers }) };
  const samples = new Float32Array([0.25, -0.25]);
  assert.equal(processor.process([[samples]]), true);
  assert.notEqual(posted[0].data, samples);
  assert.deepEqual(posted[0].data, samples);
  assert.equal(posted[0].transfers[0], posted[0].data.buffer);
  assert.equal(processor.process([]), true);
  assert.equal(posted.length, 1);
});

test("stream failures before ready fall back to the original upload using the same mic", async () => {
  for (const failure of ["error", "close", "server", "invalid"]) {
    const s = streamingSetup();
    const pending = s.input.start();
    await tick();
    s.socket().open();
    if (failure === "server") s.socket().receive({ type: "error", message: "unavailable" });
    else if (failure === "invalid") s.socket().onmessage({ data: "invalid JSON" });
    else s.socket()[`on${failure}`]();
    assert.equal(await pending, true);
    assert.equal(s.context().closed, true);
    assert.equal(s.socket().closed, true);
    assert.equal(s.stopped(), 0);
    s.input.stop(); await s.input.whenSettled();
    assert.equal(s.calls[0][0], "/api/transcribe");
    assert.equal(s.stopped(), 1);
    assert.deepEqual(s.states, ["requesting_permission", "listening", "transcribing", "idle"]);
  }
});

test("missing WebSocket or AudioContext uses the upload fallback", async () => {
  for (const option of ["WebSocket", "AudioContext"]) {
    const s = streamingSetup({ [option]: false });
    assert.equal(await s.input.start(), true);
    assert.equal(s.sockets.length, 0);
    s.input.stop(); await s.input.whenSettled();
    assert.equal(s.calls[0][0], "/api/transcribe");
  }
});

test("streaming does not require MediaRecorder or fetch", async () => {
  const s = streamingSetup({ MediaRecorder: false, fetch: false });
  await s.start();
  s.socket().receive({ type: "transcript", utterance_id: 1, text: "A race trip", is_final: true });
  s.input.stop(); s.socket().receive({ type: "ended" }); await s.input.whenSettled();
  assert.equal(s.input.getState().state, "idle");
});

test("stop before ready cancels the connection without recording, uploading, or routing", async () => {
  const s = streamingSetup();
  const pending = s.input.start();
  await tick();
  const socket = s.socket();
  socket.open();
  s.input.stop();
  assert.equal(await pending, false);
  await s.input.whenSettled();
  socket.receive({ type: "ready" });
  assert.deepEqual(s.states, ["requesting_permission", "idle"]);
  assert.equal(s.context().closed, true);
  assert.equal(s.stopped(), 1);
  assert.equal(socket.closed, true);
  assert.equal(socket.sent.length, 1);
  assert.deepEqual(s.calls, []);
});

test("stop while permission is pending releases late tracks without affecting a later run", async () => {
  let grant, stopped = 0;
  const s = setup({ getUserMedia: () => new Promise(resolve => { grant = resolve; }) });
  const pending = s.input.start();
  const completion = s.input.whenSettled();
  s.input.stop();
  await completion;
  assert.equal(await pending, false);
  grant({ getTracks: () => [{ stop: () => stopped++ }] });
  await tick();
  assert.equal(stopped, 1);
  assert.deepEqual(s.calls, []);
  assert.equal(s.input.getState().state, "idle");
});

test("partial-only or empty final transcripts fail honestly and never route", async () => {
  for (const is_final of [true, false]) {
    const s = streamingSetup();
    await s.start();
    s.socket().receive({ type: "transcript", utterance_id: 1, text: is_final ? " " : "Incomplete words", is_final });
    s.input.stop(); s.socket().receive({ type: "ended" }); await s.input.whenSettled();
    assert.equal(s.input.getState().state, "error");
    assert.equal(s.input.getState().message, "No speech detected");
    assert.deepEqual(s.calls, []);
  }
});

test("connection failures after ready never silently switch to a new recording", async () => {
  for (const failure of ["error", "close", "server", "backpressure"]) {
    const s = streamingSetup();
    await s.start();
    if (failure === "server") s.socket().receive({ type: "error", message: "unavailable" });
    else if (failure === "backpressure") { s.socket().bufferedAmount = 2 ** 21; s.samples(new Float32Array(4800)); }
    else s.socket()[`on${failure}`]();
    await s.input.whenSettled();
    assert.equal(s.input.getState().state, "error");
    assert.equal(s.stopped(), 1);
    assert.equal(s.context().closed, true);
    assert.deepEqual(s.calls, []);
  }
});

function fakeTimers() {
  const timers = new Set();
  return {
    setTimeout(callback, delay) { const timer = { callback, delay }; timers.add(timer); return timer; },
    clearTimeout(timer) { timers.delete(timer); },
    fire(delay) {
      const timer = [...timers].find(timer => timer.delay === delay);
      assert.ok(timer, `Expected a ${delay} ms timer`);
      timers.delete(timer); timer.callback();
    },
    size: () => timers.size,
  };
}

test("ready timeout falls back; both capture paths auto-stop after 120 seconds", async () => {
  for (const fallback of [true, false]) {
    const timers = fakeTimers(), s = streamingSetup(timers);
    if (fallback) {
      const pending = s.input.start(); await tick(); timers.fire(8000); await pending;
    } else await s.start();
    timers.fire(120000);
    if (!fallback) {
      assert.equal(s.input.getState().state, "transcribing");
      assert.deepEqual(JSON.parse(s.socket().sent.at(-1)), { type: "stop" });
      s.socket().receive({ type: "ended" });
    }
    await s.input.whenSettled();
    assert.equal(s.stopped(), 1);
    assert.equal(timers.size(), 0);
  }
});

test("ended timeout releases resources and allows another recording", async () => {
  const timers = fakeTimers(), s = streamingSetup(timers);
  await s.start(); s.input.stop(); timers.fire(30000); await s.input.whenSettled();
  assert.equal(s.input.getState().state, "error");
  assert.equal(s.input.getState().textFallback, true);
  await s.start();
  s.socket().receive({ type: "transcript", utterance_id: 1, text: "A race trip", is_final: true });
  s.input.stop(); s.socket().receive({ type: "ended" }); await s.input.whenSettled();
  assert.equal(s.input.getState().state, "idle");
  assert.equal(timers.size(), 0);
});
