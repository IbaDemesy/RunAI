const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const C = require("../journey-contract.js");
const P = require("../journey-player.js");

const FIXTURES = path.join(__dirname, "..", "..", "..", "runai", "contracts", "fixtures");
const load = (name) => JSON.parse(fs.readFileSync(path.join(FIXTURES, `journey_${name}.json`), "utf8"));

function fakeMap() {
  const calls = [];
  const sources = new Map();
  const layers = new Set();
  const record = (name) => (...args) => calls.push([name, ...args]);
  return {
    calls, sources, layers,
    addSource: (id, spec) => { calls.push(["addSource", id]); sources.set(id, { data: spec.data, setData(d) { this.data = d; calls.push(["setData", id]); } }); },
    getSource: (id) => sources.get(id),
    removeSource: (id) => { sources.delete(id); calls.push(["removeSource", id]); },
    addLayer: (layer) => { layers.add(layer.id); calls.push(["addLayer", layer.id]); },
    getLayer: (id) => (layers.has(id) ? { id } : undefined),
    removeLayer: (id) => { layers.delete(id); calls.push(["removeLayer", id]); },
    fitBounds: record("fitBounds"), jumpTo: record("jumpTo"), easeTo: record("easeTo"), stop: record("stop"),
  };
}

function fakeFlyover(totalM) {
  const calls = [];
  const state = { distanceM: 0, totalM, playing: false };
  return {
    calls, state,
    play: () => { calls.push(["play"]); state.playing = true; },
    pause: () => { calls.push(["pause"]); state.playing = false; },
    seekKm: (km) => { calls.push(["seekKm", km]); state.distanceM = km * 1000; },
  };
}

function fakeTimers() {
  let next = 1;
  const pending = new Map();
  return {
    pending,
    setTimeout: (fn, ms) => { const id = next++; pending.set(id, { fn, ms }); return id; },
    clearTimeout: (id) => pending.delete(id),
    runNext() {
      const [id, entry] = pending.entries().next().value || [];
      if (id === undefined) return false;
      pending.delete(id);
      entry.fn();
      return true;
    },
  };
}

function setup(options) {
  const container = new EventTarget();
  const events = [];
  for (const name of Object.values(C.MAP_EVENTS)) container.addEventListener(name, (e) => events.push([name, e.detail]));
  const map = fakeMap();
  const timers = fakeTimers();
  const flyover = options && "flyover" in options ? options.flyover : fakeFlyover(0);
  const view = P.createJourneyView(container, Object.assign({ map, flyover, setTimeout: timers.setTimeout, clearTimeout: timers.clearTimeout, dwellMs: 10, pollMs: 5 }, options));
  return { container, events, map, timers, flyover, view };
}

const of = (events, name) => events.filter(([n]) => n === name).map(([, d]) => d);

test("setPlan renders sources once, fits the global view and emits ready with revision", () => {
  const { view, map, events } = setup();
  const plan = load("train");
  assert.equal(view.setPlan(plan), true);
  assert.deepEqual([...map.sources.keys()].sort(), Object.values(P.SOURCES).sort());
  assert.equal(map.calls.filter((c) => c[0] === "fitBounds").length, 1);
  const ready = of(events, C.MAP_EVENTS.ready);
  assert.equal(ready.length, 1);
  assert.equal(ready[0].planRevision, plan.revision);
  assert.equal(ready[0].state, "overview");
  view.setPlan(load("flight"));
  assert.equal(map.calls.filter((c) => c[0] === "addSource").length, 2);
  assert.equal(map.calls.filter((c) => c[0] === "setData").length, 2);
  assert.equal(of(events, C.MAP_EVENTS.ready)[1].planRevision, 2);
});

test("segment layers distinguish modes and geometry certainty and are removed on destroy", () => {
  const { view, map } = setup();
  view.setPlan(load("train"));
  const lines = P.LAYERS.filter((layer) => layer.type === "line");
  assert.equal(lines.length, 2);
  const [solid, dashed] = lines;
  assert.deepEqual(solid.filter, ["==", ["get", "geometry_status"], "verified"]);
  assert.deepEqual(dashed.filter, ["all", ["!=", ["get", "geometry_status"], "verified"], ["!=", ["get", "geometry_status"], "unavailable"]]);
  assert.equal(solid.paint["line-dasharray"], undefined);
  assert.deepEqual(dashed.paint["line-dasharray"], [2, 2]);
  for (const layer of lines) {
    assert.equal(layer.source, P.SOURCES.segments);
    const expression = layer.paint["line-color"];
    assert.deepEqual(expression.slice(0, 2), ["match", ["get", "mode"]]);
    assert.deepEqual(expression.slice(2, -1).filter((_, i) => i % 2 === 0).sort(), [...C.SEGMENT_MODES].sort());
    assert.equal(new Set(expression.slice(2, -1).filter((_, i) => i % 2 === 1)).size, C.SEGMENT_MODES.length);
  }
  view.setPlan(load("flight"));
  assert.deepEqual([...map.layers], P.LAYERS.map((layer) => layer.id));
  assert.equal(map.calls.filter((call) => call[0] === "addLayer").length, P.LAYERS.length);
  assert.deepEqual(map.sources.get(P.SOURCES.segments).data.features.map((feature) => feature.properties.mode),
    load("flight").segments.filter((segment) => segment.geometry_status !== "unavailable").map((segment) => segment.mode));
  view.destroy();
  assert.deepEqual(map.calls.filter((call) => call[0] === "removeLayer").map((call) => call[1]), P.LAYERS.map((layer) => layer.id));
  assert.equal(map.layers.size, 0);
  assert.equal(map.sources.size, 0);
});

test("invalid plan emits error and keeps the previous plan", () => {
  const { view, events } = setup();
  view.setPlan(load("train"));
  assert.equal(view.setPlan({ schema_version: "nope" }), false);
  const [error] = of(events, C.MAP_EVENTS.error);
  assert.equal(error.error.code, "invalid_plan");
  assert.equal(error.fatal, true);
  assert.ok(error.errors.length > 0);
  assert.equal(view.state.planRevision, 1);
});

test("showChapter frames chapter bounds and emits chapter event; unknown id rejected", () => {
  const { view, map, events } = setup();
  view.setPlan(load("flight"));
  map.calls.length = 0;
  assert.equal(view.showChapter("arrival_hotel"), true);
  assert.equal(map.calls.length, 1);
  assert.equal(of(events, C.MAP_EVENTS.chapter).at(-1).chapterId, "arrival_hotel");
  assert.equal(view.showChapter("mars"), false);
  assert.equal(of(events, C.MAP_EVENTS.error).at(-1).error.code, "unknown_chapter");
});

test("unavailable chapter emits explicit unavailable + error events and never moves the camera", () => {
  const { view, map, events } = setup();
  const plan = load("incomplete");
  view.setPlan(plan);
  const unavailable = plan.chapters.filter((c) => c.status === "unavailable");
  assert.ok(unavailable.length > 0);
  for (const chapter of unavailable) {
    map.calls.length = 0;
    assert.equal(view.showChapter(chapter.id), false);
    assert.deepEqual(map.calls, []);
    const last = of(events, C.MAP_EVENTS.chapter).at(-1);
    assert.equal(last.chapterId, chapter.id);
    assert.equal(last.state, "unavailable");
    assert.equal(of(events, C.MAP_EVENTS.error).at(-1).chapterId, chapter.id);
    assert.equal(of(events, C.MAP_EVENTS.error).at(-1).fatal, false);
  }
});

test("play tours every chapter in order then ends; unavailable chapters are reported, not skipped silently", () => {
  const { view, timers, events } = setup();
  const plan = load("incomplete");
  view.setPlan(plan);
  view.play();
  while (timers.runNext());
  assert.deepEqual(of(events, C.MAP_EVENTS.chapter).map((d) => d.chapterId), plan.chapters.map((c) => c.id));
  assert.deepEqual(of(events, C.MAP_EVENTS.playback).map((d) => d.state), ["playing", "ended"]);
  assert.equal(view.state.playback, "ended");
  assert.ok(of(events, C.MAP_EVENTS.error).length > 0);
  assert.ok(of(events, C.MAP_EVENTS.error).every((detail) => detail.fatal === false));
});

test("pause stops camera only: no fetch, no agent call, pending tour cancelled, resume from paused chapter", () => {
  const originalFetch = globalThis.fetch;
  let fetched = 0;
  globalThis.fetch = () => { fetched += 1; };
  const agents = { pause: () => assert.fail("agents touched"), cancel: () => assert.fail("agents touched") };
  globalThis.RunAIAgents = agents;
  try {
    const { view, timers, events, map } = setup();
    view.setPlan(load("flight"));
    view.play();
    timers.runNext();
    const chapterBefore = view.state.chapterId;
    assert.equal(view.pause(), true);
    assert.equal(timers.pending.size, 0);
    assert.ok(map.calls.some((c) => c[0] === "stop"));
    assert.equal(of(events, C.MAP_EVENTS.playback).at(-1).state, "paused");
    assert.equal(view.pause(), false);
    view.play();
    assert.equal(of(events, C.MAP_EVENTS.chapter).at(-1).chapterId, chapterBefore);
    assert.equal(fetched, 0);
  } finally {
    globalThis.fetch = originalFetch;
    delete globalThis.RunAIAgents;
  }
});

test("race chapter plays the loaded RunAIFlyover track and waits for it before moving on", () => {
  const flyover = fakeFlyover(42000);
  const { view, timers, events } = setup({ flyover });
  view.setPlan(load("flight"));
  view.showChapter("bib_pickup");
  view.play();
  while (view.state.chapterId !== "race") timers.runNext();
  assert.deepEqual(flyover.calls, [["play"]]);
  timers.runNext();
  assert.equal(view.state.chapterId, "race");
  flyover.state.playing = false;
  while (timers.runNext());
  assert.equal(of(events, C.MAP_EVENTS.chapter).at(-1).chapterId, "return_trip");
});

test("pausing during the race pauses RunAIFlyover camera too", () => {
  const flyover = fakeFlyover(42000);
  const { view, timers } = setup({ flyover });
  view.setPlan(load("flight"));
  view.play();
  while (view.state.chapterId !== "race") timers.runNext();
  view.pause();
  assert.deepEqual(flyover.calls, [["play"], ["pause"]]);
});

test("seekKm delegates to RunAIFlyover when race geometry exists and a track is loaded", () => {
  const flyover = fakeFlyover(42000);
  const { view, events } = setup({ flyover });
  view.setPlan(load("flight"));
  assert.equal(view.seekKm(7), true);
  assert.deepEqual(flyover.calls, [["seekKm", 7]]);
  assert.equal(of(events, C.MAP_EVENTS.chapter).at(-1).chapterId, "race");
  assert.equal(view.seekKm(-1), false);
  assert.equal(of(events, C.MAP_EVENTS.error).at(-1).error.code, "invalid_km");
  assert.equal(of(events, C.MAP_EVENTS.error).at(-1).fatal, false);
});

test("seekKm refuses unavailable race geometry or missing track with an explicit error", () => {
  for (const [name, flyover] of [["train", fakeFlyover(42000)], ["flight", fakeFlyover(0)], ["flight", null]]) {
    const { view, events } = setup({ flyover });
    view.setPlan(load(name));
    assert.equal(view.seekKm(3), false);
    assert.equal(of(events, C.MAP_EVENTS.error).at(-1).error.code, "race_track_unavailable");
    if (flyover) assert.deepEqual(flyover.calls, []);
  }
});

test("new plan revision mid-tour cancels stale timers and reports stopped", () => {
  const { view, timers, events } = setup();
  view.setPlan(load("train"));
  view.play();
  view.setPlan(load("flight"));
  assert.equal(timers.pending.size, 0);
  assert.equal(of(events, C.MAP_EVENTS.playback).at(-1).state, "stopped");
  assert.equal(view.state.planRevision, 2);
});

test("reducedMotion uses instant camera moves", () => {
  const { view, map } = setup({ reducedMotion: true });
  view.setPlan(load("flight"));
  view.showChapter("race");
  for (const call of map.calls.filter((c) => c[0] === "fitBounds")) assert.equal(call[2].duration, 0);
});

test("destroy removes layers, cancels timers and rejects later calls", () => {
  const { view, map, timers, events } = setup();
  view.setPlan(load("flight"));
  view.play();
  view.destroy();
  assert.equal(map.layers.size, 0);
  assert.equal(map.sources.size, 0);
  assert.equal(timers.pending.size, 0);
  assert.equal(view.showChapter("home"), false);
  assert.equal(of(events, C.MAP_EVENTS.error).at(-1).error.code, "destroyed");
});

test("calls before setPlan emit no_plan", () => {
  const { view, events } = setup();
  assert.equal(view.play(), false);
  assert.equal(of(events, C.MAP_EVENTS.error)[0].error.code, "no_plan");
});
