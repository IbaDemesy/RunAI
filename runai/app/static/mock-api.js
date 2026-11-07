(function (root, factory) {
  const mock = factory();
  if (typeof module === "object" && module.exports) module.exports = mock;
  else root.RunAIMock = mock;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  function createAPI({ storage, loadFixture = async (name) => {
    const response = await fetch("/static/contract-fixtures/" + name + ".json");
    if (!response.ok) throw new Error("Fixtures de démonstration indisponibles. Vérifiez leur montage.");
    return response.json();
  } }) {
    let state = JSON.parse(storage.getItem("runai:mock") || "null") || { framing: null, mission: null, stage: 0, launches: 0 };
    const clone = (value) => JSON.parse(JSON.stringify(value));
    const save = () => storage.setItem("runai:mock", JSON.stringify(state));
    function fail(status, text) { const error = new Error(text); error.status = status; throw error; }
    async function fixture(name) { return clone(await loadFixture(name)); }
    async function request(path, body) {
      const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
      if (path === "/api/health") return { mode: "demo" };
      if (path === "/api/framings" && body) {
        if (state.framing) fail(409, "Une demande existe déjà.");
        state.framing = await fixture("framing_vague");
        state.framing.turns[0].text = body.text;
        save(); return clone(state.framing);
      }
      if (parts[1] === "framings") {
        const framing = state.framing;
        if (!framing || parts[2] !== framing.id) fail(404, "Demande introuvable.");
        if (!body) return clone(framing);
        if (parts[3] === "cancel") {
          if (framing.mission_id) fail(409, "Mission déjà lancée.");
          framing.status = "cancelled";
        } else if (parts[3] === "confirm") {
          if (framing.mission_id) {
            if (body.idempotency_key !== framing.confirm_key) fail(409, "Mission déjà lancée.");
            return clone(state.mission);
          }
          if (framing.status !== "ready_to_confirm" || body.revision !== framing.revision || framing.summary.revision !== body.revision) fail(409, "Résumé obsolète.");
          if (!body.idempotency_key || body.idempotency_key.length < 8) fail(422, "Clé de confirmation invalide.");
          state.mission = await fixture("mission_snapshot");
          state.mission.framing_id = framing.id; state.mission.mode = "demo";
          framing.mission_id = state.mission.mission_id;
          framing.confirm_key = body.idempotency_key; framing.status = "launched";
          state.launches += 1; save(); return clone(state.mission);
        } else if (parts[3] === "replies") {
          if (body.revision !== framing.revision || ["launched", "cancelled"].includes(framing.status)) fail(409, "Révision obsolète.");
          if (body.question_id && !framing.open_questions.some((q) => q.id === body.question_id)) fail(409, "Question obsolète.");
          if (body.choice_id && !framing.open_questions.some((q) => q.choices.some((c) => c.id === body.choice_id))) fail(409, "Choix inconnu.");
          const turn = { role: "user", channel: body.channel, text: body.text || "Correction", revision: framing.revision + 1 };
          let next;
          if (state.stage === 0) {
            next = await fixture("framing_candidates"); state.stage = 1;
          } else if (state.stage === 1) {
            const question = framing.open_questions.find((q) => q.id === body.question_id);
            const choice = question?.choices.find((c) => c.id === body.choice_id);
            if (!choice?.candidate_id) fail(422, "Choisissez une course proposée.");
            next = clone(framing); next.selected_candidate_id = choice.candidate_id;
            next.status = "collecting"; next.open_questions = []; next.candidates = [];
            const candidate = framing.candidates.find((c) => c.id === choice.candidate_id);
            next.slots.race = { name: "race", status: "sourced", value: candidate.name, revision: framing.revision + 1 };
            state.stage = 2;
          } else {
            next = await fixture("framing_ready"); state.stage = 3;
            for (const [name, value] of Object.entries(body.corrections || {})) {
              if (!next.slots[name]) fail(422, "Information inconnue.");
              next.slots[name].value = value; next.slots[name].status = "answered";
            }
            if (body.corrections && Object.keys(body.corrections).length) {
              const names = { city: "Ville", race: "Course", edition: "Édition", race_date: "Date de course", date_window: "Période", distance_km: "Distance en km", origin: "Départ", budget: "Budget", nights: "Nuits", transport_mode: "Transport", preferences: "Préférences" };
              next.summary.lines = Object.entries(next.slots).filter(([, slot]) => slot.value != null).map(([name, slot]) => names[name] + " : " + (name === "transport_mode" && slot.value === "flight" ? "Avion" : slot.value));
              if (body.corrections.budget != null) next.summary.budget_eur = Number(body.corrections.budget);
            }
          }
          next.id = framing.id; next.revision = framing.revision + 1;
          next.turns = [...framing.turns, turn]; next.mode = "demo";
          if (next.summary) next.summary.revision = next.revision;
          state.framing = next;
        } else fail(404, "Action inconnue.");
        save(); return clone(state.framing);
      }
      if (parts[1] === "missions") {
        const mission = state.mission;
        if (!mission || parts[2] !== mission.mission_id) fail(404, "Mission introuvable.");
        if (parts[3] === "journey") {
          const journey = await fixture("journey_flight");
          journey.mission_id = mission.mission_id; journey.mode = "demo"; return journey;
        }
        if (!body) return clone(mission);
        if (parts[3] === "cancel") { mission.status = "cancelled"; mission.questions.forEach((q) => { if (q.status === "open") q.status = "cancelled"; }); }
        else if (parts[3] === "questions" && parts[5] === "answer") {
          const question = mission.questions.find((q) => q.question_id === parts[4]);
          if (!question || question.status !== "open" || body.revision !== question.revision || mission.status === "cancelled") fail(409, "Question expirée ou déjà traitée.");
          if (!body.answer?.trim() || !body.idempotency_key) fail(422, "Réponse invalide.");
          question.answer = body.answer; question.status = "answered";
          mission.status = "completed"; mission.steps[0].status = "stopped_before_commitment";
          mission.steps[0].summary = "Préparé, à valider sur le site officiel.";
        } else fail(404, "Action inconnue.");
        save(); return clone(mission);
      }
      fail(404, "Route de démonstration inconnue.");
    }
    return { request, get launches() { return state.launches; } };
  }
  return { createAPI };
});
