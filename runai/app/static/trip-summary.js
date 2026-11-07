(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.tripSummary = factory();
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const money = value => new Intl.NumberFormat("en-GB", {
    style: "currency", currency: "EUR", minimumFractionDigits: 0, maximumFractionDigits: 2,
  }).format(value);
  return function tripSummary(mission = {}, framing = {}) {
    const budget = mission.budget || {};
    const race = mission.race || framing?.summary?.race || {};
    const total = { known: budget.known_total ?? null, complete: budget.complete === true,
      cap: budget.cap ?? null, overCap: budget.over_cap ?? null };
    let budgetVerdict = "Budget not assessable";
    if (total.complete && Number.isFinite(total.known) && Number.isFinite(total.cap)) {
      budgetVerdict = total.overCap === true ? "Over budget by " + money(total.known - total.cap) :
        "Within your " + money(total.cap) + " budget";
    }
    const rows = (mission.steps || []).map(step => {
      const category = ({ stay: "accommodation" })[step.kind] || step.kind;
      const lines = (budget.lines || []).filter(line => line.category === category || line.id === step.kind);
      const amount = step.price_eur ?? (lines.length && lines.every(line => Number.isFinite(line.money?.amount)) ?
        lines.reduce((sum, line) => sum + line.money.amount, 0) : null);
      let ctaUrl = null;
      try {
        const url = new URL(step.data?.manual_url || step.url);
        if (["http:", "https:"].includes(url.protocol)) ctaUrl = url.href;
      } catch (_) { /* Invalid URLs are not actionable. */ }
      return { kind: step.kind, title: ({ registration: "Registration", accommodation: "Stay", stay: "Stay", transport: "Transport" })[step.kind] || step.kind,
        status: step.status, headline: step.summary, price: Number.isFinite(amount) ? money(amount) : "Price unknown",
        stopPoint: step.status === "stopped_before_commitment" && step.stop_point === "payment" ?
          "Stopped at the payment page — nothing was paid" : null,
        ctaUrl, ctaLabel: "Finish on the official site" };
    });
    return { race: { name: race.name ?? null, date: race.race_date ?? null }, rows, total,
      verdict: "Prepared — not booked · " + budgetVerdict };
  };
});
