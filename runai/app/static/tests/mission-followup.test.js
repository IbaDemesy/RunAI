const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const core = require("../shell-core.js");

class Node {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.attributes = {}; this._text = ""; }
  set textContent(text) { this._text = text; this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(""); }
  append(...nodes) { for (const node of nodes) { node.remove(); node.parentNode = this; this.children.push(node); } }
  replaceChildren(...nodes) { for (const node of this.children) node.parentNode = null; this.children = []; this.append(...nodes); }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(node => node !== this); this.parentNode = null; }
  setAttribute(key, value) { this.attributes[key] = value; }
  querySelectorAll(selector) {
    const nodes = this.children.flatMap(child => [child, ...child.querySelectorAll()]);
    if (!selector) return nodes;
    return nodes.filter(node => {
      if ([".agent-live[open]", ".agent-history[open]"].includes(selector)) return node.className === selector.slice(1, -6) && node.open;
      if (selector.startsWith(".")) return node.className?.split(" ").includes(selector.slice(1));
      return node.tagName === selector.toUpperCase();
    });
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  contains() { return false; }
  focus() {}
}

async function setup(status = "running", questions = [], step = {}) {
  const screen = new Node("section"), feedback = new Node("p"), mode = new Node("span");
  const values = new Map([["runai:mission", "mission-test"]]), sources = [], requests = [];
  let mission = { mission_id: "mission-test", mode: "live", status, questions, limitations: [],
    steps: [{ kind: "accommodation", status: "stopped_before_commitment", stop_point: "payment",
      summary: "Arrêt avant paiement", url: "https://all.accor.com/", data: {}, ...step }] };
  class Source {
    constructor() { this.handlers = new Map(); this.closed = false; sources.push(this); }
    addEventListener(name, callback) { this.handlers.set(name, callback); }
    close() { this.closed = true; }
  }
  let voiceOptions;
  const window = { RunAIShellCore: core, EventSource: Source, addEventListener() {},
    RunAIVoiceInput: { createVoiceInput(options) { voiceOptions = options; return { state: "idle", start() {}, stop() {} }; } } };
  vm.runInNewContext(fs.readFileSync(path.resolve(__dirname, "../app.js"), "utf8"), {
    window, EventSource: Source, location: { search: "", href: "http://runai.test/" }, URLSearchParams, URL,
    sessionStorage: { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) },
    document: { activeElement: null, createElement: tag => new Node(tag), getElementById: id => ({ screen, feedback, mode }[id]) },
    async fetch(url, options) {
      requests.push({ url, options });
      const body = url === "/api/health" ? { mode: "live" } : structuredClone(mission);
      return { ok: true, json: async () => body };
    },
  });
  await new Promise(resolve => setImmediate(resolve));
  return { screen, feedback, sources, requests, voiceOptions, update: changes => { mission = { ...mission, ...changes }; } };
}

test("arrêt hôtel avant paiement sans question : action manuelle et lien officiel, aucun suivi terminal rouvert", async () => {
  const { screen, sources } = await setup("awaiting_human");
  assert.doesNotMatch(screen.textContent, /Your turn to answer/);
  assert.match(screen.textContent, /finish manually/i);
  assert.ok(screen.querySelectorAll().some(node => node.tagName === "A" && node.href === "https://all.accor.com/"));
  assert.equal(sources.length, 0);
});

test("une vraie question ouverte conserve le formulaire et la demande de réponse", async () => {
  const { screen, sources } = await setup("running", [{ question_id: "q1", step: "accommodation", status: "open",
    text: "Quelle chambre ?", choices: ["Standard"], revision: 1 }]);
  assert.match(screen.textContent, /Your turn to answer/);
  assert.ok(screen.querySelectorAll().some(node => node.tagName === "FORM"));
  assert.equal(sources.length, 1);
  assert.equal(sources[0].closed, false);
});

for (const status of ["awaiting_human", "completed", "failed", "cancelled"]) {
  test(`fin SSE ${status} : fermeture du flux et disparition de l'annonce de reconnexion`, async () => {
    const { feedback, sources, update, requests } = await setup();
    const source = sources[0];
    source.onerror();
    assert.match(feedback.textContent, /Reconnecting/);
    update({ status });
    await source.handlers.get("mission_status")();
    assert.equal(source.closed, true);
    assert.doesNotMatch(feedback.textContent, /Reconnecting/);
    if (source.onerror) source.onerror();
    assert.doesNotMatch(feedback.textContent, /Reconnecting/);
    assert.equal(sources.length, 1);
    assert.ok(requests.every(request => !request.options?.method));
  });
}

test("suivi H : dernière action lisible, historique horodaté repliable et liens live/replay distincts", async () => {
  const { screen } = await setup("running", [], { status: "running", live_view_url: "https://live.example.org/browser",
    agent_view_url: "https://platform.hcompany.ai/agent-view/test", data: { last_action: "Lecture des chambres",
      history: [{ at: "2026-11-08T10:20:30Z", message: "<script>Action H</script>" }] } });
  assert.match(screen.querySelector(".last-action").textContent, /Lecture des chambres/);
  const history = screen.querySelector(".agent-history");
  assert.equal(!!history.open, false);
  assert.equal(history.querySelector("time").attributes.datetime, "2026-11-08T10:20:30Z");
  assert.match(history.textContent, /<script>Action H<\/script>/);
  const replay = screen.querySelectorAll("a").find(node => node.textContent === "Replay");
  assert.equal(replay.href, "https://platform.hcompany.ai/agent-view/test");
  assert.equal(replay.target, "_blank");
  const live = screen.querySelectorAll("a").find(node => node.textContent === "Watch the agent live");
  assert.equal(live.href, "https://live.example.org/browser");
});

test("fenêtre live HTTPS repliable, agrandissable, conservée au rafraîchissement et retirée en fin d'étape", async () => {
  const step = { kind: "accommodation", status: "running", live_view_url: "https://live.example.org/browser", data: {} };
  const { screen, sources, update } = await setup("running", [], step);
  const panel = screen.querySelector(".agent-live");
  assert.ok(panel);
  const frame = screen.querySelector("iframe");
  assert.ok(frame, "the live view opens by itself while the agent is working");
  assert.equal(frame.src, "https://live.example.org/browser");
  assert.equal(frame.attributes.sandbox, "allow-scripts allow-same-origin");
  const enlarge = panel.querySelectorAll("button").find(node => node.textContent === "Enlarge");
  enlarge.onclick();
  assert.equal(screen.querySelector(".step").dataset.expanded, "true");
  const fallback = panel.querySelectorAll("a").find(node => node.textContent === "Open in a tab");
  assert.equal(fallback.href, frame.src);
  update({ steps: [{ ...step, data: { last_action: "Navigation suivante" } }] });
  await sources[0].handlers.get("trace")();
  assert.equal(screen.querySelector("iframe"), frame);
  assert.match(screen.querySelector(".last-action").textContent, /Navigation suivante/);
  update({ status: "awaiting_human", steps: [{ ...step, status: "stopped_before_commitment", url: "https://all.accor.com/" }] });
  await sources[0].handlers.get("mission_status")();
  assert.equal(screen.querySelector("iframe"), null);
  assert.match(screen.textContent, /Finish it yourself/);
});

for (const url of [null, "http://live.example.org/browser", "javascript:alert(1)"]) {
  test(`URL live ${url} : aucune iframe non HTTPS et historique vide explicite`, async () => {
    const { screen } = await setup("running", [], { status: "running", live_view_url: url, agent_view_url: "javascript:alert(2)" });
    assert.equal(screen.querySelector(".agent-live"), null);
    assert.equal(screen.querySelector("iframe"), null);
    assert.match(screen.textContent, /No events received/);
    assert.equal(screen.querySelectorAll("a").some(node => node.href.startsWith("javascript:")), false);
  });
}

test("commande vocale avec fenêtre live ouverte : les boutons restent utilisables après la mutation", async () => {
  const { screen, voiceOptions } = await setup("running", [], { status: "running", live_view_url: "https://live.example.org/browser" });
  const panel = screen.querySelector(".agent-live"); panel.open = true; panel.ontoggle();
  screen.querySelectorAll("button").find(node => node.textContent === "Speak").onclick();
  await voiceOptions.onAgentsCommand("pause");
  assert.ok(screen.querySelectorAll("button").every(node => !node.disabled));
  assert.equal(screen.querySelector(".agent-live"), panel);
});

test("sans LiveViewURL, les observations H affichent une capture proxifiée révisée et le lien replay reste séparé", async () => {
  const step = { kind: "accommodation", status: "running", agent_view_url: "https://platform.hcompany.ai/agents/sessions/s1",
    data: { browser_observation: { revision: 1, url: "https://all.accor.com/", title: "Chambres disponibles" } } };
  const { screen, sources, update } = await setup("running", [], step);
  const panel = screen.querySelector(".agent-live");
  assert.ok(panel);
  panel.open = true; panel.ontoggle();
  const image = screen.querySelector("img");
  assert.equal(image.src, "/api/missions/mission-test/steps/accommodation/screenshot?v=1");
  assert.match(panel.textContent, /Chambres disponibles/);
  assert.equal(screen.querySelector("iframe"), null);
  update({ steps: [{ ...step, data: { browser_observation: { revision: 2, url: "https://all.accor.com/rooms", title: "Tarifs" } } }] });
  await sources[0].handlers.get("trace")();
  assert.equal(screen.querySelector("img"), image);
  assert.equal(image.src, "/api/missions/mission-test/steps/accommodation/screenshot?v=2");
  assert.match(panel.textContent, /Tarifs/);
  image.onerror();
  assert.match(panel.textContent, /Preview unavailable/);
  assert.equal(screen.querySelectorAll("a").some(node => node.textContent === "Replay"), true);
});

test("la première capture apparaît aussi quand la fenêtre live est déjà ouverte", async () => {
  const step = { kind: "accommodation", status: "running", live_view_url: "https://live.example.org/browser", data: {} };
  const { screen, sources, update } = await setup("running", [], step);
  const panel = screen.querySelector(".agent-live"); panel.open = true; panel.ontoggle();
  assert.equal(panel.querySelector("img"), null);
  update({ steps: [{ ...step, data: { browser_observation: { revision: 1, title: "Première capture", url: "https://example.com/" } } }] });
  await sources[0].handlers.get("trace")();
  assert.equal(screen.querySelector(".agent-live"), panel);
  assert.equal(panel.querySelector("img")?.src, "/api/missions/mission-test/steps/accommodation/screenshot?v=1");
});
