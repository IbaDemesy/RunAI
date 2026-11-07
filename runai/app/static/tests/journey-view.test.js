const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

function setup(withMap = true) {
  const calls = [], handlers = new Map();
  class DetailEvent extends Event {
    constructor(type, options) { super(type, options); this.detail = options.detail; }
  }
  const target = new EventTarget(), container = new EventTarget();
  container.parentNode = target;
  const events = { error: "runai:journey-error", ready: "runai:journey-ready", chapter: "runai:journey-chapter", playback: "runai:journey-playback" };
  const make = kind => ({
    setPlan: plan => calls.push([kind, "plan", plan]),
    destroy: () => calls.push([kind, "destroy"]),
    pause: () => calls.push([kind, "pause"]),
    play: () => calls.push([kind, "play"]),
    showChapter: id => calls.push([kind, "chapter", id]),
    seekKm: km => calls.push([kind, "km", km]),
  });
  const window = {
    CustomEvent: DetailEvent, RunAIJourneyContract: { MAP_EVENTS: events },
    RunAIJourneyPlayer: { createJourneyView: () => { calls.push(["player", "create"]); return make("player"); } },
    RunAIJourneyFallback: { createJourneyView: () => make("timeline") },
  };
  if (withMap) window.maplibregl = { Map: class {
    on(name, callback) { handlers.set(name, callback); }
    off(name) { handlers.delete(name); }
    remove() { calls.push(["map", "remove"]); }
  } };
  vm.runInNewContext(fs.readFileSync(path.resolve(__dirname, "../journey-view.js"), "utf8"), { window });
  const view = window.RunAIJourneyView.createJourneyView(container, {
    timelineContainer: {}, errorTarget: target, reducedMotion: true,
    onEvent: (name, detail) => calls.push(["shell", name, detail]),
  });
  return { view, calls, handlers, container, target, events, DetailEvent };
}

test("le même plan va au repli puis au player après load, jamais avant", () => {
  const { view, calls, handlers } = setup();
  const plan = { revision: 3 };
  view.setPlan(plan);
  assert.deepEqual(calls, [["timeline", "plan", plan]]);
  handlers.get("load")();
  assert.deepEqual(calls.slice(-2), [["player", "create"], ["player", "plan", plan]]);
  view.showChapter("return_trip"); view.pause();
  assert.ok(calls.some(c => c[0] === "timeline" && c[1] === "chapter"));
  assert.ok(calls.some(c => c[0] === "player" && c[1] === "pause"));
  view.destroy(); view.destroy();
  assert.equal(calls.filter(c => c[0] === "map" && c[1] === "remove").length, 1);
  assert.equal(handlers.size, 0);
});

test("chapitre non fatal conservé ; erreur tuiles fatale relayée, carte détruite, timeline préservée", () => {
  const { view, calls, handlers, target, events, DetailEvent, container } = setup();
  view.setPlan({}); handlers.get("load")();
  target.dispatchEvent(new DetailEvent(events.error, { detail: { fatal: false } }));
  assert.equal(calls.filter(c => c[0] === "map").length, 0);
  handlers.get("error")();
  assert.equal(container.hidden, true);
  assert.equal(calls.filter(c => c[0] === "map" && c[1] === "remove").length, 1);
  assert.ok(calls.some(c => c[0] === "shell" && c[2].fatal === true));
  assert.equal(calls.filter(c => c[0] === "timeline" && c[1] === "destroy").length, 0);
  view.play();
  assert.deepEqual(calls.at(-1), ["timeline", "play"]);
  view.destroy();
});

test("MapLibre absent et plan vide : erreur explicite, repli toujours connecté", () => {
  const { view, calls, container } = setup(false);
  assert.equal(container.hidden, true);
  assert.ok(calls.some(c => c[0] === "shell" && c[2].fatal));
  view.setPlan(null);
  assert.deepEqual(calls.at(-1), ["timeline", "plan", null]);
  view.seekKm(2);
  assert.deepEqual(calls.at(-1), ["timeline", "km", 2]);
  view.destroy();
});
