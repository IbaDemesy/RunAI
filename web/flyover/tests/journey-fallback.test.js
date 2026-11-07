const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const J = require("../journey-contract.js");

const fixtures = path.join(__dirname, "../../../runai/contracts/fixtures");
const load = (name = "train") => JSON.parse(fs.readFileSync(path.join(fixtures, `journey_${name}.json`), "utf8"));
const sourcePath = path.join(__dirname, "../journey-fallback.js");

// A minimal DOM boundary for Node unit tests, not a browser/accessibility audit.
class Element extends EventTarget {
  constructor(tag, doc) {
    super();
    this.tagName = tag.toUpperCase();
    this.ownerDocument = doc;
    this.children = [];
    this.attributes = {};
    this.hidden = false;
    this.parentNode = null;
    this._text = "";
  }
  set textContent(value) { this._text = String(value); this.replaceChildren(); }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  removeAttribute(name) { delete this.attributes[name]; }
  append(...children) {
    for (const child of children) { child.remove(); this.children.push(child); child.parentNode = this; }
  }
  replaceChildren(...children) {
    for (const child of this.children) child.parentNode = null;
    this.children = [];
    this.append(...children);
  }
  remove() {
    if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((n) => n !== this);
    this.parentNode = null;
  }
  contains(node) { return node === this || this.children.some((c) => c.contains(node)); }
  focus() { this.ownerDocument.activeElement = this; }
}

function descendants(node, predicate) {
  return node.children.flatMap((child) => [...(predicate(child) ? [child] : []), ...descendants(child, predicate)]);
}
const byAttr = (node, key, value) => descendants(node, (c) => c.getAttribute(key) === value)[0];
const byTag = (node, tag) => descendants(node, (c) => c.tagName === tag.toUpperCase());

function setup(options = {}) {
  const doc = { createElement: (tag) => new Element(tag, doc), activeElement: null };
  const timers = new Map();
  let nextTimer = 0;
  class DetailEvent extends Event { constructor(type, init) { super(type, init); this.detail = init.detail; } }
  const media = new EventTarget();
  media.matches = !!options.matches;
  const browser = {
    CustomEvent: DetailEvent,
    matchMedia: () => media,
    setTimeout: (fn) => { timers.set(++nextTimer, fn); return nextTimer; },
    clearTimeout: (id) => timers.delete(id),
  };
  doc.defaultView = browser;
  const context = { self: {}, URL, console, ...browser };
  context.self.RunAIJourneyContract = J;
  context.self.RunAIRoute = require("../route.js");
  vm.runInNewContext(fs.readFileSync(sourcePath, "utf8"), context);
  const container = doc.createElement("div");
  const events = [];
  Object.values(J.MAP_EVENTS).forEach((name) => container.addEventListener(name, (e) => events.push(e)));
  const view = context.self.RunAIJourneyFallback.createJourneyView(container, options);
  const interact = (target, type, key) => {
    const event = new Event(type, { cancelable: true });
    Object.defineProperty(event, "target", { value: target });
    if (key) Object.defineProperty(event, "key", { value: key });
    for (let node = target; node; node = node.parentNode) node.dispatchEvent(event);
    return event;
  };
  return { doc, container, view, events, timers, media, interact, DetailEvent };
}

for (const [name, total] of [["train", "503"], ["flight", "540"], ["incomplete", "250"]]) {
  test(`${name}: all seven chapters, stops, limits, provenance and budget are readable without a map`, () => {
    const { container, view, events } = setup();
    const plan = load(name);
    view.setPlan(plan);
    assert.equal(byTag(container, "nav").length, 1);
    assert.equal(byTag(container, "article").length, 7);
    for (const chapter of plan.chapters) assert.ok(container.textContent.includes(chapter.label));
    for (const stop of plan.stops) assert.ok(container.textContent.includes(stop.label));
    for (const warning of plan.warnings) assert.ok(container.textContent.includes(warning));
    assert.match(container.textContent, /Démonstration/);
    assert.ok(container.textContent.includes(total));
    assert.match(container.textContent, /fictif|Fixture/);
    assert.match(container.textContent, /Illustratif/);
    assert.match(container.textContent, /Vérifié/);
    assert.equal(events.filter((e) => e.type === J.MAP_EVENTS.ready).at(-1).detail.planRevision, plan.revision);
    assert.equal(byTag(container, "canvas").length + byTag(container, "img").length + byTag(container, "iframe").length, 0);
    view.destroy();
  });
}

test("unknown coordinates, dates and money remain unknown; manual links and non-coverage stay visible", () => {
  const { container, view } = setup();
  view.setPlan(load("incomplete"));
  assert.match(container.textContent, /Localisation non renseignée/);
  assert.match(container.textContent, /Horaire non renseigné/);
  assert.match(container.textContent, /Total partiel/);
  assert.match(container.textContent, /Prix inconnu/);
  assert.match(container.textContent, /Plafond non vérifiable/);
  assert.match(container.textContent, /Transport hors Europe non automatisé/);
  assert.ok(byTag(container, "a").some((a) => a.getAttribute("href") === "https://example.org/airline-search"));
  assert.doesNotMatch(container.textContent, /réservé avec succès|budget respecté/i);
});

test("native chapter buttons support arrows/Home/End without stealing focus on programmatic updates", () => {
  const { container, view, doc, interact, events } = setup();
  view.setPlan(load());
  const first = byAttr(container, "data-chapter", "home");
  first.focus();
  assert.equal(first.tagName, "BUTTON");
  assert.equal(first.getAttribute("type"), "button");
  assert.equal(interact(first, "keydown", "ArrowRight").defaultPrevented, true);
  assert.equal(doc.activeElement.getAttribute("data-chapter"), "departure_hub");
  assert.equal(doc.activeElement.getAttribute("aria-current"), "step");
  interact(doc.activeElement, "keydown", "End");
  assert.equal(doc.activeElement.getAttribute("data-chapter"), "return_trip");
  interact(doc.activeElement, "keydown", "Home");
  assert.equal(doc.activeElement, first);
  assert.equal(interact(first, "keydown", "Tab").defaultPrevented, false);
  view.showChapter("race");
  assert.equal(doc.activeElement, first);
  assert.equal(events.at(-1).detail.chapterId, "race");
  assert.throws(() => view.showChapter("fake"), /chapitre/i);
});

test("plan replacement keeps chapter focus, discards previous content and cancels playback", () => {
  const { container, view, doc, timers, interact } = setup();
  view.setPlan(load());
  const race = byAttr(container, "data-chapter", "race");
  interact(race, "click");
  race.focus();
  view.play();
  assert.equal(timers.size, 1);
  view.setPlan(load("incomplete"));
  assert.equal(timers.size, 0);
  assert.equal(doc.activeElement.getAttribute("data-chapter"), "race");
  assert.ok(container.contains(doc.activeElement));
  assert.doesNotMatch(container.textContent, /Lille/);
  assert.match(container.textContent, /Lyon/);
});

test("play advances once per chapter; pause and destroy clear resources and detach handlers", () => {
  const { container, view, timers, events, interact, DetailEvent } = setup();
  view.setPlan(load());
  interact(byAttr(container, "data-action", "play"), "click");
  const [id, tick] = [...timers][0];
  timers.delete(id);
  tick();
  assert.equal(byAttr(container, "data-chapter", "departure_hub").getAttribute("aria-current"), "step");
  assert.equal(timers.size, 1);
  view.pause();
  assert.equal(timers.size, 0);
  view.play();
  view.destroy();
  view.destroy();
  assert.equal(container.children.length, 0);
  assert.equal(timers.size, 0);
  const count = events.length;
  container.dispatchEvent(new DetailEvent(J.MAP_EVENTS.error, { detail: { error: "webgl" } }));
  view.play();
  assert.equal(events.length, count + 1); // Only our externally dispatched error.
  assert.equal(timers.size, 0);
});

test("reduced motion forbids automatic playback, including a preference change during play", () => {
  const fixed = setup({ reducedMotion: true });
  fixed.view.setPlan(load());
  fixed.view.play();
  assert.equal(fixed.timers.size, 0);
  assert.match(fixed.container.textContent, /Mouvement réduit/);
  fixed.view.showChapter("race");
  assert.equal(byAttr(fixed.container, "data-chapter", "race").getAttribute("aria-current"), "step");
  const dynamic = setup();
  dynamic.view.setPlan(load());
  dynamic.view.play();
  dynamic.media.matches = true;
  dynamic.media.dispatchEvent(new Event("change"));
  assert.equal(dynamic.timers.size, 0);
  dynamic.view.destroy();
  dynamic.media.matches = false;
  dynamic.media.dispatchEvent(new Event("change"));
  assert.equal(dynamic.container.children.length, 0);
});

test("tile/WebGL error reveals fallback and pauses; stale revision errors do not affect the new plan", () => {
  const { container, view, timers, DetailEvent } = setup({ hiddenUntilError: true });
  view.setPlan(load());
  const root = container.children[0];
  assert.equal(root.hidden, true);
  container.dispatchEvent(new DetailEvent(J.MAP_EVENTS.error, { detail: { planRevision: 0, error: "tiles" } }));
  assert.equal(root.hidden, true);
  view.play();
  container.dispatchEvent(new DetailEvent(J.MAP_EVENTS.error, { detail: { planRevision: 1, error: "webgl" } }));
  assert.equal(root.hidden, false);
  assert.equal(timers.size, 0);
  assert.match(root.textContent, /Carte indisponible/);
  assert.match(root.textContent, /Lille/);
});

test("nonfatal journey errors neither reveal fallback nor pause playback", () => {
  const { container, view, timers, DetailEvent } = setup({ hiddenUntilError: true });
  view.setPlan(load());
  view.play();
  const root = container.children[0];
  const pending = [...timers.keys()];
  container.dispatchEvent(new DetailEvent(J.MAP_EVENTS.error, {
    detail: { planRevision: 1, fatal: false, error: { code: "chapter_unavailable" } },
  }));
  assert.equal(root.hidden, true);
  assert.deepEqual([...timers.keys()], pending);
  assert.doesNotMatch(root.textContent, /Carte indisponible/);
  container.dispatchEvent(new DetailEvent(J.MAP_EVENTS.error, { detail: { error: "tiles" } }));
  assert.equal(root.hidden, false);
  assert.equal(timers.size, 0);
  assert.match(root.textContent, /Carte indisponible/);
});

test("sources and attributions stay visible and untrusted labels/URLs cannot inject markup or scripts", () => {
  const { container, view } = setup({ attributions: [{ label: "© Test cartographe", url: "https://example.org/credits" }] });
  const plan = load();
  plan.stops[0].label = '<img src=x onerror="alert(1)">';
  plan.sources.push({ kind: "linkup", label: "Malicious", url: "javascript:alert(1)", collected_at: "2026-11-07T12:00:00Z" });
  plan.segments[1].manual_url = "data:text/html,bad";
  view.setPlan(plan);
  assert.ok(container.textContent.includes('<img src=x onerror="alert(1)">'));
  assert.equal(byTag(container, "img").length, 0);
  assert.match(container.textContent, /© Test cartographe/);
  assert.match(container.textContent, /2026-11-07/);
  for (const a of byTag(container, "a")) assert.match(a.getAttribute("href"), /^https?:\/\//);
});

test("invalid replacement clears stale data and surfaces a contract error", () => {
  const { container, view, timers } = setup();
  view.setPlan(load());
  view.play();
  const bad = load();
  bad.segments[0].to_stop_id = "absent";
  assert.throws(() => view.setPlan(bad), /JourneyPlan/);
  assert.equal(timers.size, 0);
  assert.doesNotMatch(container.textContent, /Lille/);
  assert.match(container.textContent, /Séjour indisponible/);
});

test("seek never invents kilometres when a race geometry is unavailable", () => {
  const { container, view } = setup();
  view.setPlan(load());
  assert.equal(view.seekKm(10), false);
  assert.match(container.textContent, /Distance non disponible/);
  assert.throws(() => view.seekKm(-1), /distance/i);
});

test("seek clamps to the supplied race geometry and keeps its illustrative label", () => {
  const { container, view, events } = setup();
  const plan = load("flight");
  plan.segments.find((s) => s.mode === "race").geometry = [[0, 0], [0, 0.018]];
  view.setPlan(plan);
  const km = view.seekKm(100);
  assert.ok(km > 2 && km < 2.01);
  assert.equal(events.at(-1).detail.km, km);
  assert.match(container.textContent, /Illustratif/);
});

test("plan replacement restores focus to a retained playback control", () => {
  const { container, view, doc } = setup();
  view.setPlan(load());
  byAttr(container, "data-action", "next").focus();
  view.setPlan(load("flight"));
  assert.equal(doc.activeElement.getAttribute("data-action"), "next");
  assert.ok(container.contains(doc.activeElement));
});

test("a hidden fallback does not start a background playback timer", () => {
  const { view, timers } = setup({ hiddenUntilError: true });
  view.setPlan(load());
  view.play();
  assert.equal(timers.size, 0);
});

test("replacing a playing plan moves focus from disabled Pause to an available control", () => {
  const { container, view, doc } = setup();
  view.setPlan(load());
  view.play();
  byAttr(container, "data-action", "pause").focus();
  view.setPlan(load("flight"));
  assert.ok(container.contains(doc.activeElement));
  assert.equal(doc.activeElement.disabled, false);
});

test("the map failure explanation survives chapter navigation", () => {
  const { container, view, DetailEvent } = setup();
  view.setPlan(load());
  container.dispatchEvent(new DetailEvent(J.MAP_EVENTS.error, { detail: { error: "tiles" } }));
  view.showChapter("race");
  assert.match(container.textContent, /Carte indisponible/);
});

test("a map error before setPlan does not leave an unavailable-journey warning after a valid plan loads", () => {
  const { container, view, DetailEvent } = setup();
  container.dispatchEvent(new DetailEvent(J.MAP_EVENTS.error, { detail: { error: "webgl" } }));
  assert.match(container.textContent, /Séjour indisponible/);
  view.setPlan(load("incomplete"));
  view.showChapter("race");
  assert.doesNotMatch(container.textContent, /Séjour indisponible/);
  assert.match(container.textContent, /Carte indisponible/);
  assert.match(container.textContent, /Mon séjour, étape par étape/);
});
