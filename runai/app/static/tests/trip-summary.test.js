const { test } = require("node:test");
const assert = require("node:assert/strict");
const tripSummary = require("../trip-summary.js");
const fixture = require("../../../contracts/fixtures/mission_snapshot.json");

test("snapshot keeps partial budgets unassessable and unknown prices explicit", () => {
  const result = tripSummary(fixture);
  assert.match(result.verdict, /Prepared — not booked/);
  assert.match(result.verdict, /Budget not assessable/);
  assert.ok(result.rows.some(row => row.price === "Price unknown"));
  assert.equal(result.rows[1].stopPoint, "Stopped at the payment page — nothing was paid");
  assert.equal(result.rows[2].ctaUrl, "https://example.org/airline-search");
});

test("whole euro prices and complete budget verdicts", () => {
  const mission = structuredClone(fixture);
  mission.steps[0].price_eur = 800;
  mission.budget = { known_total: 920, cap: 800, complete: true, over_cap: true };
  const result = tripSummary(mission);
  assert.equal(result.rows[0].price, "€800");
  assert.match(result.verdict, /Over budget by €120/);
  mission.budget.known_total = 800; mission.budget.over_cap = false;
  assert.match(tripSummary(mission).verdict, /Within your €800 budget/);
});

test("empty snapshots and unsafe links do not invent evidence", () => {
  assert.deepEqual(tripSummary().rows, []);
  assert.match(tripSummary().verdict, /Budget not assessable/);
  for (const url of ["javascript:alert(1)", "invalid", "file:///secret"]) {
    const result = tripSummary({ steps: [{ kind: "stay", url, summary: "Ready" }] });
    assert.equal(result.rows[0].ctaUrl, null);
    assert.equal(result.rows[0].price, "Price unknown");
  }
});

test("matching budget lines supply prices without treating missing amounts as zero", () => {
  const mission = { steps: [{ kind: "stay" }], budget: { lines: [
    { category: "accommodation", money: { amount: 1234 } },
  ] } };
  assert.equal(tripSummary(mission).rows[0].price, "€1,234");
  mission.budget.lines.push({ category: "accommodation", money: null });
  assert.equal(tripSummary(mission).rows[0].price, "Price unknown");
});
