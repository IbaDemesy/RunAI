const { test } = require("node:test");
const assert = require("node:assert/strict");
const { partnerFor, decorate } = require("../partners.js");
const fs = require("node:fs");
const vm = require("node:vm");

class Node {
  constructor(tag, doc) { this.tagName = tag.toUpperCase(); this.ownerDocument = doc; this.children = []; this.attributes = {}; this.className = ""; this.textContent = ""; }
  append(...nodes) { for (const node of nodes) { node.parentNode = this; this.children.push(node); } }
  setAttribute(key, value) { this.attributes[key] = value; }
  getAttribute(key) { return this.attributes[key]; }
  insertBefore(node, reference) { node.parentNode = this; this.children.splice(reference ? this.children.indexOf(reference) : this.children.length, 0, node); }
  querySelectorAll(selector) { return this.children.flatMap(child => [...(child.className.split(" ").includes(selector.slice(1)) ? [child] : []), ...child.querySelectorAll(selector)]); }
}
test("J3 partner attribution requires explicit live mode and provider", () => {
  for (const provider of ["h", "linkup", "holo4", "gladia"]) {
    assert.equal(partnerFor({ mode: "demo", provider }).label, "Demo");
    assert.equal(partnerFor({ mode: "replay", provider }).label, "Recorded");
    assert.equal(partnerFor({ provider }), null);
  }
  for (const context of [{ source: "h" }, { sources: [{}] }, { role: "assistant" }, { voice: true }]) {
    assert.equal(partnerFor({ mode: "live", ...context }), null);
  }
  assert.equal(partnerFor({ mode: "live", provider: "h" }).label, "H web-surfer-pro");
  assert.equal(partnerFor({ mode: "live", provider: "linkup", sources: [{}], latency_ms: 1250 }).label, "Found by Linkup · 1 source · 1.3 s");
  assert.equal(partnerFor({ framing: { mode: "live", turns: [{ role: "assistant", provider: "holo4" }] } }).id, "holo");
  assert.equal(partnerFor({ mode: "live", provider: "unknown", source: "h" }), null);
  assert.equal(partnerFor(), null);
});
test("decoration is idempotent and sources only link to HTTP or HTTPS", () => {
  const doc = { createElement: tag => new Node(tag, doc), getElementById: () => mode };
  const screen = doc.createElement("section"), header = doc.createElement("header"), mode = doc.createElement("span");
  header.append(mode);
  const card = doc.createElement("article"); card.className = "candidate";
  const heading = doc.createElement("h2"); heading.textContent = "Trail <safe>"; card.append(heading);
  for (const className of ["say", "voice-controls", "lane"]) { const node = doc.createElement("div"); node.className = className; screen.append(node); }
  screen.append(card);
  const sources = [{ url: "https://example.org/race", title: "<safe>" }, { url: "http://example.net" }, { url: "javascript:alert(1)" }, { url: "data:text/html,test" }, { url: "invalid" }];
  const ctx = { framing: { mode: "demo", candidates: [{ name: heading.textContent, sources }], turns: [] } };
  decorate(screen, ctx); decorate(screen, ctx);
  assert.equal(screen.querySelectorAll(".partner-badge").length, 3);
  assert.equal(header.querySelectorAll(".powered-by").length, 1);
  const details = card.querySelectorAll(".sources"); assert.equal(details.length, 1);
  const links = details[0].children[1].children.map(li => li.children[0]);
  assert.equal(links.length, 2); assert.equal(links[0].textContent, "<safe>"); assert.equal(links[1].textContent, "example.net");
  for (const link of links) { assert.equal(link.target, "_blank"); assert.equal(link.rel, "noopener noreferrer"); }
});
test("empty contexts, missing header insertion and unmatched cards are safe", () => {
  const doc = { createElement: tag => new Node(tag, doc), getElementById: () => ({}) };
  const screen = doc.createElement("section"), card = doc.createElement("article"); card.className = "candidate"; screen.append(card);
  decorate(screen); decorate(null);
  assert.equal(card.children.length, 0);
});
test("J3 agent badges use the actual step kind, not DOM order", () => {
  const doc = { createElement: tag => new Node(tag, doc) };
  const registration = doc.createElement("article"), hotel = doc.createElement("article");
  registration.dataset = { kind: "registration" }; hotel.dataset = { kind: "accommodation" };
  const screen = { ownerDocument: doc, querySelectorAll: selector => selector === ".step[data-kind]" ? [hotel, registration] : [] };
  decorate(screen, { mission: { mode: "live", steps: [{ kind: "registration", provider: "h" }, { kind: "accommodation", provider: "demo" }] } });
  assert.equal(registration.children[0].textContent, "H web-surfer-pro");
  assert.equal(hotel.children.length, 0);
});
test("voice controls show English actions, attribution and only nonempty listening partials", () => {
  const source = fs.readFileSync(require.resolve("../app.js"), "utf8");
  const controls = source.slice(source.indexOf("  function voiceControls()"), source.indexOf("  function slotText("));
  for (const state of [{ state: "listening", partial: "<spoken>" }, { state: "listening", partial: "" }, { state: "idle", partial: "hidden" }, { state: "listening" }]) {
    const doc = { createElement: tag => new Node(tag, doc) }, screen = doc.createElement("section");
    screen.querySelector = () => null;
    const el = (tag, text, className) => { const node = doc.createElement(tag); node.textContent = text || ""; node.className = className || ""; return node; };
    vm.runInNewContext(controls + "voiceControls();", { voice: { getState: () => state }, voiceState: state.state, screen, mission: null, framing: { mode: "demo" }, el, button: text => el("button", text) });
    const partials = screen.querySelectorAll(".voice-partial");
    assert.equal(partials.length, state.state === "listening" && state.partial ? 1 : 0);
    if (partials.length) { assert.equal(partials[0].textContent, "<spoken>"); assert.equal(partials[0].getAttribute("aria-live"), "polite"); }
    assert.equal(screen.querySelectorAll(".partner-badge").length, 1);
    assert.equal(screen.querySelectorAll(".partner-badge")[0].textContent, "Demo voice");
    assert.equal(screen.children[0].children[0].textContent, state.state === "listening" ? "Stop recording" : "Speak");
  }
});
