(function (root, factory) {
  const core = factory();
  if (typeof module === "object" && module.exports) module.exports = core;
  else root.RunAIShellCore = core;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  function replyPayload(framing, text, options = {}) {
    const payload = { revision: framing.revision, channel: options.channel || "text", text };
    for (const key of ["question_id", "choice_id", "corrections"]) {
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
  function framingState(framing) { return framing.mission_id ? "launched" : framing.status; }
  function budgetText(budget) {
    if (!budget) return { lines: [], total: "Budget pending", cap: "cap not assessable" };
    const money = (value) => new Intl.NumberFormat("en-GB", { style: "currency", currency: budget.currency }).format(value);
    return {
      lines: budget.lines.map((line) => line.label + " : " + (line.money ? money(line.money.amount) : "Price unknown") + (line.note ? " — " + line.note : "")),
      total: (budget.complete ? "Total" : "Known total (partial budget)") + " : " + money(budget.known_total),
      cap: budget.over_cap == null ? "cap not assessable" : (budget.over_cap ? "Over cap" : "Within cap") + (budget.cap == null ? "" : " : " + money(budget.cap)),
    };
  }
  return { replyPayload, idempotencyKey, framingState, budgetText };
});
