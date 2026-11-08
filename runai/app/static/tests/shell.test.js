const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const core = require("../shell-core.js");
const { createAPI } = require("../mock-api.js");
const fixture = async (name) => JSON.parse(await fs.readFile(path.resolve(__dirname, "../../../contracts/fixtures", name + ".json"), "utf8"));
function memory() {
  const values = new Map();
  return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
}
test("réponses : révision serveur, voix, choix et corrections sans champ inventé", async () => {
  const framing = await fixture("framing_candidates");
  const question = framing.open_questions[0];
  const choice = question.choices[0];
  assert.deepEqual(core.replyPayload(framing, choice.label, { question_id: question.id, choice_id: choice.id, channel: "buttons", candidate_id: "ignoré" }),
    { revision: framing.revision, text: choice.label, question_id: question.id, choice_id: choice.id, channel: "buttons" });
  assert.deepEqual(core.replyPayload(framing, "Nouvelle valeur", { channel: "voice", corrections: { origin: "Départ consenti" } }),
    { revision: framing.revision, text: "Nouvelle valeur", channel: "voice", corrections: { origin: "Départ consenti" } });
  assert.deepEqual(core.replyPayload(framing, ""), { revision: framing.revision, text: "", channel: "text" });
});
test("clé persistante par cadrage et révision, y compris après reprise", () => {
  const storage = memory();
  assert.equal(core.idempotencyKey(storage, "f", 5, () => "clé-initiale"), "clé-initiale");
  assert.equal(core.idempotencyKey(storage, "f", 5, () => { throw Error("nouvelle clé interdite"); }), "clé-initiale");
  assert.equal(core.idempotencyKey(storage, "f", 6, () => "autre-clé"), "autre-clé");
});
test("tous les états de cadrage sont conservés sans lancement implicite", () => {
  for (const status of ["collecting", "choosing_candidate", "ready_to_confirm", "confirmed", "launched", "cancelled"]) {
    assert.equal(core.framingState({ status, mission_id: null }), status);
  }
  assert.equal(core.framingState({ status: "confirmed", mission_id: "serveur" }), "launched");
});
test("AC-56: budget partiel, vide, nul et complet : aucun prix manquant inventé", async () => {
  const { budget } = await fixture("mission_snapshot");
  const text = core.budgetText(budget);
  assert.match(text.total, /250/);
  assert.match(text.total, /partial/);
  assert.match(text.lines[1], /Price unknown/);
  assert.match(text.cap, /Cap €2,000.*known total €250.*partial/);
  assert.doesNotMatch(text.total, /\.00/);
  assert.match(core.budgetText({ ...budget, known_total: 118.5 }).total, /€118\.50/);
  assert.equal(core.budgetText(null).total, "Budget pending");
  assert.deepEqual(core.budgetText({ ...budget, lines: [] }).lines, []);
  assert.match(core.budgetText({ ...budget, complete: true, over_cap: true }).cap, /Over cap/);
  assert.match(core.budgetText({ ...budget, complete: true, over_cap: false }).cap, /Within cap/);
});
async function ready(api) {
  let f = await api.request("/api/framings", { text: "Ma demande", channel: "text" });
  assert.equal(f.status, "collecting");
  const base = "/api/framings/" + f.id;
  const initial = f.revision;
  f = await api.request(base + "/replies", core.replyPayload(f, "Une course au printemps"));
  assert.equal(f.status, "choosing_candidate");
  await assert.rejects(api.request(base + "/replies", { revision: initial, text: "Périmé" }), { status: 409 });
  const q = f.open_questions[0], c = q.choices[1];
  f = await api.request(base + "/replies", core.replyPayload(f, c.label, { question_id: q.id, choice_id: c.id, channel: "buttons" }));
  assert.equal(f.status, "collecting");
  assert.equal(f.selected_candidate_id, c.candidate_id);
  f = await api.request(base + "/replies", core.replyPayload(f, "Correction de budget", { corrections: { budget: 1800 } }));
  assert.equal(f.status, "ready_to_confirm");
  assert.equal(f.summary.revision, f.revision);
  return { f, base };
}
test("démo complète : vague → choix → correction → confirmation unique → réponse → séjour", async () => {
  const storage = memory();
  let api = createAPI({ storage, loadFixture: fixture });
  const { f, base } = await ready(api);
  assert.equal(api.launches, 0);
  await assert.rejects(api.request(base + "/confirm", { revision: f.revision - 1, idempotency_key: "clé-confirmation" }), { status: 409 });
  const confirmation = { revision: f.summary.revision, idempotency_key: "clé-confirmation" };
  const mission = await api.request(base + "/confirm", confirmation);
  assert.equal(mission.mode, "demo");
  assert.deepEqual(await api.request(base + "/confirm", confirmation), mission);
  assert.equal(api.launches, 1);
  api = createAPI({ storage, loadFixture: fixture });
  assert.equal((await api.request(base)).mission_id, mission.mission_id);
  assert.deepEqual(await api.request(base + "/confirm", confirmation), mission);
  assert.equal(api.launches, 1);
  await assert.rejects(api.request(base + "/confirm", { ...confirmation, idempotency_key: "autre-clé" }), { status: 409 });
  const q = mission.questions[0], route = "/api/missions/" + mission.mission_id;
  await assert.rejects(api.request(route + "/questions/" + q.question_id + "/answer", { answer: "Non", revision: q.revision - 1, idempotency_key: "clé-réponse" }), { status: 409 });
  const result = await api.request(route + "/questions/" + q.question_id + "/answer", { answer: "Non", revision: q.revision, idempotency_key: "clé-réponse" });
  assert.equal(result.questions[0].status, "answered");
  assert.equal(result.status, "completed");
  await assert.rejects(api.request(route + "/questions/" + q.question_id + "/answer", { answer: "Oui", revision: q.revision, idempotency_key: "autre-clé" }), { status: 409 });
  const journey = await api.request(route + "/journey");
  assert.equal(journey.mission_id, mission.mission_id);
  assert.ok(journey.chapters.length);
});
test("annulation et erreurs : aucune mission sans confirmation explicite", async () => {
  const api = createAPI({ storage: memory(), loadFixture: fixture });
  await assert.rejects(api.request("/api/missions/inconnu"), { status: 404 });
  const f = await api.request("/api/framings", { text: "Course", channel: "text" });
  const route = "/api/framings/" + f.id;
  await assert.rejects(api.request(route + "/confirm", { revision: f.revision, idempotency_key: "confirmation" }), { status: 409 });
  assert.equal((await api.request(route + "/cancel", {})).status, "cancelled");
  await assert.rejects(api.request(route + "/replies", core.replyPayload(f, "Suite")), { status: 409 });
  assert.equal(api.launches, 0);
});
test("fixture absente : échec explicite, aucun état créé", async () => {
  const api = createAPI({ storage: memory(), loadFixture: async () => { throw Error("fixture absente"); } });
  await assert.rejects(api.request("/api/framings", { text: "Course" }), /fixture absente/);
  assert.equal(api.launches, 0);
});
