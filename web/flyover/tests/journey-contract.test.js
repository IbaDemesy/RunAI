const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const J = require("../journey-contract.js");

const FIXTURES = path.join(__dirname, "..", "..", "..", "runai", "contracts", "fixtures");
const load = (name) => JSON.parse(fs.readFileSync(path.join(FIXTURES, name), "utf8"));

for (const name of ["journey_train.json", "journey_flight.json", "journey_incomplete.json"]) {
  test(`${name} satisfies the JS contract`, () => {
    const plan = load(name);
    assert.deepEqual(J.validateJourneyPlan(plan), []);
    assert.deepEqual(plan.chapters.map((c) => c.id), J.CHAPTER_IDS);
  });
}

test("incomplete fixture keeps unknown coordinates null and budget partial", () => {
  const plan = load("journey_incomplete.json");
  assert.ok(plan.stops.some((s) => s.coords === null));
  assert.equal(plan.budget.complete, false);
  assert.equal(plan.budget.over_cap, null);
});

test("dangling references and fake geometry are rejected", () => {
  const plan = load("journey_train.json");
  plan.segments[0].to_stop_id = "nowhere";
  plan.segments[5].geometry = [[0, 0], [1, 1]];
  const errors = J.validateJourneyPlan(plan);
  assert.ok(errors.some((e) => e.includes("nowhere")));
  assert.ok(errors.some((e) => e.startsWith("geometry")));
});
