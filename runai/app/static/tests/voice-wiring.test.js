const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const core = require("../shell-core.js");

class Node {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.attributes = {}; this.textContent = ""; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(key, value) { this.attributes[key] = value; }
  querySelectorAll() { return this.children.flatMap(child => [child, ...child.querySelectorAll()]); }
  querySelector() { return null; }
  contains() { return false; }
  focus() {}
}

async function setup(withMission = false, question = null, slots = {}) {
  const screen = new Node("section"), feedback = new Node("p"), badge = new Node("span");
  const calls = [], listeners = {};
  const values = new Map(withMission ? [["runai:mission", "m-test"]] : []);
  const session = revision => ({ id: "f-test", revision, mode: "demo", status: "collecting", turns: [], open_questions: question ? [question] : [], candidates: [], limitations: [], slots });
  let current = session(1), conflict = false, options;
  const mission = { mission_id: "m-test", status: "running", mode: "demo", steps: [], questions: [], limitations: [] };
  const window = {
    RunAIShellCore: core,
    RunAIVoiceInput: { createVoiceInput(value) { options = value; return { start() {}, stop() {} }; } },
    addEventListener(name, callback) { listeners[name] = callback; },
  };
  const context = {
    window, location: { search: "", href: "http://runai.test/" }, URLSearchParams, URL, console,
    sessionStorage: { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) },
    document: { activeElement: null, getElementById: id => ({ screen, feedback, mode: badge }[id]), createElement: tag => new Node(tag) },
    async fetch(url, request = {}) {
      const payload = request.body ? JSON.parse(request.body) : undefined;
      calls.push({ url, payload });
      if (url.endsWith("/replies") && conflict) return { ok: false, status: 409 };
      let result;
      if (url === "/api/health") result = { mode: "demo" };
      else if (url === "/api/framings") result = current;
      else if (url.endsWith("/replies")) result = current = session(current.revision + 1);
      else if (url.startsWith("/api/missions/")) result = mission;
      else result = current;
      return { ok: true, json: async () => result };
    },
  };
  vm.runInNewContext(fs.readFileSync(path.resolve(__dirname, "../app.js"), "utf8"), context);
  await new Promise(resolve => setImmediate(resolve));
  const speak = () => screen.querySelectorAll().find(node => node.textContent === "Parler").onclick();
  return { options, calls, speak, listeners, screen, badge, feedback, conflict: () => { conflict = true; } };
}

test("English shell labels, compact budget, sourced date and accessible actions", async () => {
  const question = { id: "origin", text: "Where are you leaving from?", choices: [], allow_free_text: true };
  const { options, screen, badge, speak } = await setup(false, question, {
    budget: { status: "answered", value: 800.0 },
    race_date: { status: "sourced", value: "2027-04-01" },
    date_window: { status: "missing", value: null },
  });
  assert.equal(badge.textContent, "Mode: Demo");
  assert.ok(screen.querySelectorAll().some(node => node.textContent === "Where do you want to run?"));
  speak(); await options.onFramingReply({ text: "A spring marathon, from Lyon", revision: 0 });
  const nodes = screen.querySelectorAll();
  assert.ok(nodes.some(node => node.textContent === "€800 max"));
  assert.equal(nodes.some(node => node.textContent === "Period ?"), false);
  assert.ok(nodes.some(node => node.textContent === "Send" && node.attributes["aria-label"].includes(question.text)));
  assert.ok(nodes.some(node => node.textContent === "Edit" && node.attributes["aria-label"] === "Edit · Budget"));
});

test("Empty dates retain the period prompt; request conflicts use English feedback", async () => {
  const { options, screen, feedback, conflict, speak } = await setup(false, null, { date_window: { status: "missing", value: null } });
  speak(); await options.onFramingReply({ text: "A race", revision: 0 });
  assert.ok(screen.querySelectorAll().some(node => node.textContent === "Period ?"));
  speak(); conflict();
  assert.equal(await windowlessReply(options), false);
  assert.equal(feedback.textContent, "Conversation updated.");
});

async function windowlessReply(options) {
  try { await options.onFramingReply({ text: "More details", revision: 1 }); }
  catch (error) { assert.match(error.message, /non appliquée/); return false; }
  return true;
}

test("voix initiale et multi-tours utilisent framing, aucune mission directe ; version périmée non envoyée", async () => {
  const { options, speak, calls, conflict } = await setup();
  speak(); await options.onFramingReply({ text: "une course", revision: 0 });
  assert.equal(options.getRevision(), 1);
  assert.deepEqual(calls.find(call => call.url === "/api/framings").payload, { text: "une course", channel: "voice" });
  speak(); await options.onFramingReply({ text: "précision", revision: 1 });
  assert.equal(options.getRevision(), 2);
  const count = calls.filter(call => call.url.endsWith("/replies")).length;
  await assert.rejects(options.onFramingReply({ text: "ancienne réponse", revision: 1 }), /expired/);
  assert.equal(calls.filter(call => call.url.endsWith("/replies")).length, count);
  speak(); conflict();
  await assert.rejects(options.onFramingReply({ text: "réponse en conflit", revision: 2 }), /non appliquée/);
  assert.equal(calls.some(call => call.url === "/api/missions"), false);
});

test("pause/reprise vocales appellent les agents, pas la caméra ; page quittée rejette les commandes", async () => {
  const { options, speak, calls, listeners } = await setup(true);
  speak(); await options.onAgentsCommand("pause");
  speak(); await options.onAgentsCommand("resume");
  assert.ok(calls.some(call => call.url === "/api/missions/m-test/pause"));
  assert.ok(calls.some(call => call.url === "/api/missions/m-test/resume"));
  const count = calls.length;
  assert.throws(() => options.view.pause(), /Explorer/);
  assert.equal(calls.length, count);
  listeners.pagehide();
  await assert.rejects(options.onAgentsCommand("pause"), /plus active/);
  assert.equal(calls.length, count);
});

test("une ville vocale brève répond à la question ouverte comme le formulaire texte", async () => {
  const question = { id: "city-question", text: "Dans quelle ville ?", slots: ["city"], choices: [], allow_free_text: true };
  const { options, speak, calls } = await setup(false, question);
  speak(); await options.onFramingReply({ text: "une course", revision: 0 });
  speak(); await options.onFramingReply({ text: "Tokyo", revision: 1 });
  const payload = calls.find(call => call.url.endsWith("/replies")).payload;
  assert.equal(payload.question_id, question.id);
  assert.equal(payload.text, "Tokyo");
  assert.equal(payload.channel, "voice");
  assert.equal(payload.revision, 1);
});
