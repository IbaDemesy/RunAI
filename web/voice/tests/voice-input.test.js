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
    getUserMedia: async () => ({ getTracks: () => [{ stop: () => stopped++ }] }),
    MediaRecorder: Recorder,
    fetch: async (url, init) => {
      calls.push([url, init]);
      return { ok: true, json: async () => ({ text: "Je veux préparer mon séjour" }) };
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
  assert.deepEqual(calls[1], { revision: 4, text: "Je veux préparer mon séjour", channel: "voice" });
});

test("permission denied and unsupported retain text fallback", async () => {
  const denied = setup({ getUserMedia: async () => { throw Object.assign(new Error("refusé"), { name: "NotAllowedError" }); } });
  await denied.input.start();
  assert.equal(denied.input.getState().state, "permission_denied");
  assert.equal(denied.input.getState().textFallback, true);
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
