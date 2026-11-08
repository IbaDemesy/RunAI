const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../shell-core.js");

test("five stages with two explicit steps between the search and the trip proposal", () => {
  assert.deepEqual(core.STAGES, ["Search", "Pick your race", "Confirm your trip", "Agents at work", "Your trip"]);
});

test("journeyStage follows the framing status, then the mission", () => {
  assert.equal(core.journeyStage(null, null), 0);
  assert.equal(core.journeyStage({ status: "collecting" }, null), 0);
  assert.equal(core.journeyStage({ status: "choosing_candidate" }, null), 1);
  assert.equal(core.journeyStage({ status: "ready_to_confirm" }, null), 2);
  assert.equal(core.journeyStage({ status: "launched", mission_id: "m1" }, null), 3);
  assert.equal(core.journeyStage({ status: "launched" }, { status: "running" }), 3);
  assert.equal(core.journeyStage({ status: "launched" }, { status: "awaiting_human" }), 4);
  assert.equal(core.journeyStage({ status: "launched" }, { status: "completed" }), 4);
  assert.equal(core.journeyStage({ status: "weird" }, null), 0);
});
