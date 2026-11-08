const { test } = require("node:test");
const assert = require("node:assert/strict");
const core = require("../shell-core.js");

test("a 409 refusal shows the server guidance, other failures stay generic", () => {
  assert.equal(core.errorMessage(409, "Please specify the race city you want instead."), "Please specify the race city you want instead.");
  assert.equal(core.errorMessage(422, "[{\"loc\": [\"body\"]}]"), "The request failed (422). Try again.");
  assert.equal(core.errorMessage(409, "{\"raw\": 1}"), "The request failed (409). Try again.");
  assert.equal(core.errorMessage(500, "boom"), "The request failed (500). Try again.");
  assert.equal(core.errorMessage(409, ""), "The request failed (409). Try again.");
  assert.equal(core.errorMessage(409, "x".repeat(301)), "The request failed (409). Try again.");
});

test("only stale-revision refusals are reported as a silent refresh", () => {
  assert.equal(core.isStale("Stale revision 3 (current 4)"), true);
  assert.equal(core.isStale("Stale or unknown question"), true);
  assert.equal(core.isStale(""), true);
  assert.equal(core.isStale("Please enter a valid number for nights."), false);
});

test("a client message id is forwarded so a double send is applied once", () => {
  const payload = core.replyPayload({ revision: 2 }, "my reply", { client_message_id: "m-1", question_id: "q" });
  assert.equal(payload.client_message_id, "m-1");
  assert.equal("client_message_id" in core.replyPayload({ revision: 2 }, "my reply"), false);
});
