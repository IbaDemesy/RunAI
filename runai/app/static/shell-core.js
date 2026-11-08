(function (root, factory) {
  const core = factory();
  if (typeof module === "object" && module.exports) module.exports = core;
  else root.RunAIShellCore = core;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  function replyPayload(framing, text, options = {}) {
    const payload = { revision: framing.revision, channel: options.channel || "text", text };
    for (const key of ["question_id", "choice_id", "corrections", "client_message_id"]) {
      if (options[key] !== undefined) payload[key] = options[key];
    }
    return payload;
  }
  function idempotencyKey(storage, id, revision, generate) {
    const name = "runai:key:" + id + ":" + revision;
    let key = storage.getItem(name);
    if (!key) { key = generate(); storage.setItem(name, key); }
    return key;
  }
  // Server refusals (409) carry a user-safe explanation; anything else stays generic (never raw validation dumps).
  function errorMessage(status, detail) {
    if ([400, 409].includes(status) && typeof detail === "string" && detail.trim() && detail.length <= 300 && !/^[\[{]/.test(detail.trim())) return detail.trim();
    return "The request failed (" + status + "). Try again.";
  }
  function isStale(detail) { return !detail || /^Stale (?:revision|or unknown question)/i.test(detail); }
  function framingState(framing) { return framing.mission_id ? "launched" : framing.status; }
  // Search -> two explicit steps (pick the race, confirm the trip) -> agents live -> the trip proposal.
  const STAGES = ["Search", "Pick your race", "Confirm your trip", "Agents at work", "Your trip"];
  function journeyStage(framing, mission) {
    if (mission) return ["completed", "awaiting_human"].includes(mission.status) ? 4 : 3;
    if (!framing) return 0;
    const byStatus = { collecting: 0, choosing_candidate: 1, ready_to_confirm: 2, confirmed: 3, launched: 3 };
    return framing.mission_id ? 3 : (byStatus[framing.status] ?? 0);
  }
  function budgetText(budget) {
    if (!budget) return { lines: [], total: "Budget pending", cap: "cap not assessable" };
    const money = (value) => new Intl.NumberFormat("en-GB", { style: "currency", currency: budget.currency, minimumFractionDigits: Number.isInteger(value) ? 0 : 2, maximumFractionDigits: 2 }).format(value);
    return {
      lines: budget.lines.map((line) => line.label + " : " + (line.money ? money(line.money.amount) : "Price unknown") + (line.note ? " — " + line.note : "")),
      total: (budget.complete ? "Total" : "Known total (partial budget)") + " : " + money(budget.known_total),
      cap: budget.cap == null ? "cap not assessable" : budget.over_cap == null
        ? "Cap " + money(budget.cap) + " · known total " + money(budget.known_total) + " (partial)"
        : (budget.over_cap ? "Over cap" : "Within cap") + " : " + money(budget.cap),
    };
  }
  return { replyPayload, idempotencyKey, errorMessage, isStale, framingState, budgetText, STAGES, journeyStage };
});
