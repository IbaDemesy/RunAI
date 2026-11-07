/* Shell V2 : toute mutation passe par cette API remplaçable. */
(function () {
  "use strict";
  const core = window.RunAIShellCore;
  const screen = document.getElementById("screen");
  const feedback = document.getElementById("feedback");
  const storage = sessionStorage;
  const mock = new URLSearchParams(location.search).get("mock") === "1" || window.RUNAI_MOCK;
  const api = mock ? window.RunAIMock.createAPI({ storage }) : {
    async request(path, body) {
      const response = await fetch(path, body === undefined ? {} : {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      if (!response.ok) { const error = new Error("La demande a échoué (" + response.status + "). Réessayez."); error.status = response.status; throw error; }
      return response.json();
    },
  };
  let framing, mission, events, view, plan, busy = false, page = "progress";
  const drafts = new Map();
  let journeyScripts;
  function loadJourneyScripts() {
    if (!journeyScripts) journeyScripts = (window.RUNAI_JOURNEY_SCRIPTS || []).reduce((previous, src) => previous.then(() => new Promise((resolve) => {
      const script = document.createElement("script");
      script.src = src; script.onload = resolve; script.onerror = resolve;
      document.head.append(script);
    })), Promise.resolve());
    return journeyScripts;
  }
  const labels = {
    registration: "Inscription", accommodation: "Hôtel", transport: "Transport",
    pending: "En attente", searching: "Recherche en cours", running: "En cours", paused: "En pause",
    waiting_for_user: "À vous de répondre", awaiting_human: "À vous de répondre",
    stopped_before_commitment: "Préparé, avant engagement", completed: "Préparé",
    failed: "Échec", cancelled: "Annulé", open: "Ouverte", answered: "Réponse acceptée",
    expired: "Expirée", refused: "Refusée", payment: "Paiement", account: "Création de compte",
    consent: "Consentement", verified: "Vérifié", estimated: "Estimé", illustrative: "Illustratif",
    unknown: "Inconnu", fixture: "Démonstration", live: "Réel", replay: "Replay",
    flight: "Avion", train: "Train", car: "Voiture", bus: "Autocar", local: "Transport local",
    city: "Ville", race: "Course", edition: "Édition", race_date: "Date de course",
    date_window: "Période", distance_km: "Distance (km)", origin: "Départ", budget: "Budget",
    nights: "Nuits", transport_mode: "Mode de transport", preferences: "Préférences",
  };
  const label = (value) => labels[value] || value || "inconnu";
  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function button(text, action, primary = false) {
    const node = el("button", text, primary ? "primary" : "secondary");
    node.type = "button"; node.disabled = busy;
    node.onclick = () => action(); return node;
  }
  function link(parent, url, text) {
    if (!url) return;
    try {
      const parsed = new URL(url);
      if (!["https:", "http:"].includes(parsed.protocol)) return;
      const node = el("a", text || url); node.href = parsed.href;
      node.target = "_blank"; node.rel = "noopener noreferrer"; parent.append(node);
    } catch (_) { /* Une source invalide ne devient pas un lien. */ }
  }
  function announce(text) { feedback.textContent = text; }
  function mode(value) {
    document.getElementById("mode").textContent = ({ live: "Réel · live", demo: "Démonstration · demo", replay: "Relecture · replay" })[value] || "Mode non vérifié";
  }
  function key(id, revision) { return core.idempotencyKey(storage, id, revision, () => crypto.randomUUID()); }
  function persist() {
    if (framing) storage.setItem("runai:framing", framing.id);
    if (mission) storage.setItem("runai:mission", mission.mission_id);
  }
  function form(parent, title, onSubmit, draftKey, value = "") {
    const node = el("form", null, "answer-form");
    const fieldLabel = el("label", title);
    const input = el("input"); input.required = true; input.maxLength = 1000;
    input.value = drafts.get(draftKey) || value;
    input.oninput = () => drafts.set(draftKey, input.value);
    fieldLabel.append(input);
    const submit = button("Envoyer", () => {}, true); submit.type = "submit";
    node.append(fieldLabel, submit);
    node.onsubmit = (event) => { event.preventDefault(); if (!busy && input.value.trim()) onSubmit(input.value.trim()); };
    parent.append(node);
  }
  function limitations(parent, values = []) {
    for (const item of values) {
      const row = el("p", item.message, "hint"); link(row, item.manual_url, " Ouvrir le site officiel"); parent.append(row);
    }
  }
  function provenance(parent, money) {
    if (!money) return;
    parent.append(el("p", [label(money.confidence), money.provenance?.label, money.collected_at].filter(Boolean).join(" · "), "hint"));
    link(parent, money.provenance?.url, "Source");
  }
  function destroyView() { if (view) { view.destroy(); view = null; } }
  function render() {
    const active = document.activeElement;
    const focusKey = active?.dataset.focusKey;
    const selection = active?.selectionStart;
    destroyView(); screen.replaceChildren();
    if (mission) { mode(mission.mode); renderMission(); }
    else if (framing) { mode(framing.mode); renderFraming(); }
    else renderStart();
    screen.querySelectorAll("input").forEach((input, index) => { input.dataset.focusKey = String(index); });
    if (focusKey != null) {
      const input = screen.querySelector('[data-focus-key="' + focusKey + '"]');
      if (input) { input.focus(); if (selection != null) input.setSelectionRange(selection, selection); }
    }
  }
  async function mutate(action, reload) {
    if (busy) return;
    busy = true; screen.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    announce("Envoi en cours…");
    try { await action(); persist(); announce("Demande acceptée."); }
    catch (error) {
      if (error.status === 409 && reload) {
        try { await reload(); announce("Cette version a changé ou la réponse a expiré. Données actualisées : vérifiez avant de répondre à nouveau."); }
        catch (_) { announce("Actualisation impossible. Rechargez la page pour reprendre sans relancer."); }
      } else announce(error.message || "Connexion indisponible. Réessayez.");
    } finally { busy = false; render(); }
  }
  async function reloadFraming() {
    framing = await api.request("/api/framings/" + encodeURIComponent(framing.id));
    if (framing.mission_id) await loadMission(framing.mission_id);
  }
  async function submitReply(text, options = {}) {
    if (!framing || mission) return;
    return mutate(async () => {
      framing = await api.request("/api/framings/" + encodeURIComponent(framing.id) + "/replies", core.replyPayload(framing, text, options));
      drafts.clear();
    }, reloadFraming);
  }
  function renderStart() {
    screen.className = "hero";
    screen.append(el("h1", "Préparer ma course"), el("p", "Inscription, hôtel, transport : un séjour préparé, sans paiement ni engagement automatique.", "hero-sub"));
    const node = el("form", null, "ask");
    const fieldLabel = el("label", "Quelle course et quel séjour souhaitez-vous préparer ?");
    const input = el("textarea"); input.required = true; input.maxLength = 1000; input.name = "text"; fieldLabel.append(input);
    const submit = button("Préparer mon séjour", () => {}, true); submit.type = "submit";
    node.append(fieldLabel, submit);
    node.onsubmit = (event) => { event.preventDefault(); mutate(async () => {
      framing = await api.request("/api/framings", { text: input.value.trim(), channel: "text" });
    }); };
    screen.append(node);
  }
  function renderFraming() {
    screen.className = "shell-stack";
    screen.append(el("h1", "Compléter ma demande"));
    const state = core.framingState(framing);
    if (state === "cancelled") { screen.append(el("p", "Demande annulée. Aucun agent lancé.")); return; }
    const thread = el("ol", null, "thread");
    for (const turn of framing.turns) thread.append(el("li", (turn.role === "user" ? "Vous : " : "RunAI : ") + turn.text));
    screen.append(thread);
    for (const question of framing.open_questions) {
      const block = el("article", null, "agent-question"); block.append(el("h2", question.text));
      const choices = el("div", null, "question-options");
      for (const choice of question.choices) choices.append(button(choice.label, () => submitReply(choice.label, { channel: "buttons", question_id: question.id, choice_id: choice.id })));
      block.append(choices);
      if (question.allow_free_text) form(block, "Votre réponse", (text) => submitReply(text, { question_id: question.id }), question.id);
      screen.append(block);
    }
    for (const candidate of framing.candidates) {
      const block = el("article", null, "step");
      block.append(el("h2", candidate.name), el("p", [candidate.city, candidate.country, candidate.race_date || "Date inconnue", candidate.distances_km.join(" / ") + " km"].join(" · ")));
      const question = framing.open_questions.find((q) => q.choices.some((c) => c.candidate_id === candidate.id));
      const choice = question?.choices.find((c) => c.candidate_id === candidate.id);
      if (choice) block.append(button("Choisir cette course", () => submitReply(choice.label, { channel: "buttons", question_id: question.id, choice_id: choice.id })));
      link(block, candidate.official_url || candidate.sources[0]?.url, "Source officielle");
      limitations(block, candidate.limitations); screen.append(block);
    }
    const slots = el("details", null, "trace"); slots.open = true; slots.append(el("summary", "Informations connues et corrections"));
    for (const [name, slot] of Object.entries(framing.slots)) {
      const known = ["answered", "sourced", "not_needed"].includes(slot.status);
      const row = el("div", null, "slot-row");
      row.append(el("p", label(name) + " : " + (known ? (slot.value == null ? "Sans objet" : typeof slot.value === "object" ? JSON.stringify(slot.value) : label(slot.value)) : "inconnu")));
      row.append(button("Corriger · " + label(name), () => {
        const editor = el("div"); row.append(editor);
        form(editor, "Nouvelle valeur : " + label(name), (text) => submitReply(text, { corrections: { [name]: text } }), "slot:" + name);
        editor.querySelector("input").focus();
      }));
      slots.append(row);
    }
    screen.append(slots);
    if (!framing.open_questions.length && state !== "ready_to_confirm") form(screen, "Compléter ou corriger votre demande", submitReply, "reply");
    if (state === "ready_to_confirm" && framing.summary) {
      const summary = el("section", null, "bib shell-stack"); summary.append(el("h2", "Votre demande, avant lancement"));
      framing.summary.lines.forEach((line) => summary.append(el("p", line)));
      limitations(summary, framing.summary.limitations);
      summary.append(button("Confirmer et lancer les agents", () => mutate(async () => {
        const result = await api.request("/api/framings/" + encodeURIComponent(framing.id) + "/confirm", {
          revision: framing.summary.revision, idempotency_key: key(framing.id, framing.summary.revision),
        });
        mission = result; framing.mission_id = result.mission_id; subscribe();
      }, reloadFraming), true)); screen.append(summary);
    }
    limitations(screen, framing.limitations);
    screen.append(button("Annuler la demande", () => mutate(async () => {
      framing = await api.request("/api/framings/" + encodeURIComponent(framing.id) + "/cancel", {});
    }, reloadFraming)));
  }
  async function loadMission(id) {
    mission = await api.request("/api/missions/" + encodeURIComponent(id)); persist(); subscribe();
  }
  function subscribe() {
    if (events) events.close();
    if (mock || !window.EventSource || ["completed", "cancelled", "failed"].includes(mission.status)) return;
    events = new EventSource("/api/missions/" + encodeURIComponent(mission.mission_id) + "/events");
    const refresh = async () => {
      try {
        mission = await api.request("/api/missions/" + encodeURIComponent(mission.mission_id));
        if (!busy && !screen.querySelector("input:focus, textarea:focus")) render();
      }
      catch (_) { announce("Suivi interrompu. La reconnexion ne relance pas les agents."); }
    };
    for (const name of ["message", "snapshot", "mission_status", "step", "question_opened", "question_resolved", "journey_revised", "budget_updated", "trace"]) events.addEventListener(name, refresh);
    events.onerror = () => announce("Reconnexion au suivi en cours…");
  }
  function questionBlock(question) {
    const block = el("article", null, "agent-question");
    block.append(el("h3", question.text), el("p", label(question.step) + " · " + label(question.status)));
    if (question.reason) block.append(el("p", question.reason));
    if (question.status !== "open") { if (question.answer) block.append(el("p", question.answer)); return block; }
    const answer = (text) => mutate(async () => {
      mission = await api.request("/api/missions/" + encodeURIComponent(mission.mission_id) + "/questions/" + encodeURIComponent(question.question_id) + "/answer", {
        answer: text, revision: question.revision, idempotency_key: key(question.question_id, question.revision),
      }); drafts.delete(question.question_id);
    }, () => loadMission(mission.mission_id));
    const choices = el("div", null, "question-options");
    question.choices.forEach((choice) => choices.append(button(choice, () => answer(choice))));
    block.append(choices); form(block, "Votre réponse", answer, question.question_id);
    return block;
  }
  function renderMission() {
    screen.className = "shell-stack";
    const questions = mission.questions || [];
    if (questions.some((q) => q.status === "open")) {
      const priority = el("section", null, "questions"); priority.append(el("h1", "À vous de répondre"));
      questions.filter((q) => q.status === "open").forEach((q) => priority.append(questionBlock(q))); screen.append(priority);
    }
    const nav = el("nav", null, "question-options"); nav.setAttribute("aria-label", "Écrans du séjour");
    [["progress", "Préparatifs en cours"], ["stay", "Mon séjour"], ["explore", "Explorer"]].forEach(([id, title]) => nav.append(button(title, () => { page = id; render(); })));
    screen.append(nav, el("h2", page === "stay" ? "Mon séjour" : page === "explore" ? "Explorer" : "Préparatifs en cours"), el("p", label(mission.status)));
    if (mission.error) screen.append(el("p", mission.error));
    if (page === "explore") { renderExplorer(); return; }
    if (page === "stay") {
      screen.append(el("p", "Séjour préparé · aucun engagement automatique."), el("h3", mission.race?.name || "Course en préparation"),
        el("p", "Date de course : " + (mission.race?.race_date || "inconnue")));
      if (framing?.summary) screen.append(el("p", framing.summary.date_range.join(" → ")));
      const budget = core.budgetText(mission.budget);
      budget.lines.forEach((line, index) => { screen.append(el("p", line)); provenance(screen, mission.budget.lines[index].money); });
      screen.append(el("p", budget.total, "total"), el("p", budget.cap));
      for (const id of mission.budget?.missing_line_ids || []) {
        if (!mission.budget.lines.some((line) => line.id === id)) screen.append(el("p", "Poste manquant : Prix inconnu"));
      }
    }
    const steps = el("div", null, "steps");
    for (const step of mission.steps) {
      const block = el("article", null, "step");
      block.append(el("h3", label(step.kind)), el("p", label(step.status), "status"), el("p", step.summary || "En attente"));
      if (step.stop_point) block.append(el("p", "Point d’arrêt : " + label(step.stop_point)));
      if (step.error) block.append(el("p", step.error));
      link(block, step.data?.manual_url || step.url, "Continuer manuellement sur le site officiel");
      const details = el("details"); details.append(el("summary", "Détails techniques"), el("p", step.h_session_id || "Session non disponible"));
      link(details, step.live_view_url, "Ouvrir la vue de l’agent"); block.append(details); steps.append(block);
    }
    screen.append(steps); limitations(screen, mission.limitations);
    questions.filter((q) => q.status !== "open").forEach((q) => screen.append(questionBlock(q)));
    if (mission.status !== "cancelled") screen.append(button("Annuler les préparatifs", () => mutate(async () => {
      mission = await api.request("/api/missions/" + encodeURIComponent(mission.mission_id) + "/cancel", {});
      if (events) events.close();
    }, () => loadMission(mission.mission_id))));
  }
  async function renderExplorer() {
    const container = el("div", null, "journey-map"); container.setAttribute("aria-label", "Carte du séjour");
    const fallback = el("section", null, "shell-stack");
    screen.append(container, fallback);
    try {
      plan = await api.request("/api/missions/" + encodeURIComponent(mission.mission_id) + "/journey");
      await loadJourneyScripts();
      if (page !== "explore" || !container.isConnected) return;
      const errors = window.RunAIJourneyContract?.validateJourneyPlan(plan) || [];
      if (errors.length) throw new Error("Le parcours reçu est invalide. Réessayez après actualisation.");
      mode(plan.mode);
      fallback.append(el("h3", "Parcours accessible"));
      for (const chapter of plan.chapters) {
        const block = el("article", null, "step"); block.append(el("h3", chapter.label));
        for (const id of chapter.stop_ids) { const stop = plan.stops.find((s) => s.id === id); if (stop) block.append(el("p", stop.label + " · " + label(stop.confidence))); }
        for (const id of chapter.segment_ids) { const segment = plan.segments.find((s) => s.id === id); if (segment) block.append(el("p", "Géométrie : " + label(segment.geometry_status))); }
        fallback.append(block);
      }
      (plan.warnings || []).forEach((warning) => fallback.append(el("p", warning)));
      limitations(fallback, plan.limitations);
      const controls = el("div", null, "question-options"); screen.insertBefore(controls, container);
      function mapError() { destroyView(); container.hidden = true; announce("Carte indisponible. Le parcours reste disponible dans la liste."); }
      container.addEventListener(window.RunAIJourneyContract?.MAP_EVENTS.error || "runai:journey-error", mapError);
      if (typeof window.createJourneyView === "function") {
        try {
          view = window.createJourneyView(container, { reducedMotion: matchMedia("(prefers-reduced-motion: reduce)").matches });
          view.setPlan(plan);
          plan.chapters.forEach((chapter) => controls.append(button(chapter.label, () => view?.showChapter(chapter.id))));
          controls.append(button("Lecture", () => view?.play()), button("Pause", () => view?.pause()));
        } catch (_) { mapError(); }
      } else container.hidden = true;
    } catch (error) {
      fallback.append(el("p", error.message), button("Réessayer", render));
    }
  }
  window.RunAIShell = { api, submitReply };
  window.addEventListener("pagehide", () => { destroyView(); if (events) events.close(); });
  async function init() {
    render();
    try {
      if (mock) mode("demo");
      else {
        try { const health = await api.request("/api/health"); mode(health.mode); }
        catch (_) { mode(null); announce("Mode indisponible. Vérifiez la connexion avant de préparer votre demande."); }
      }
      const missionId = storage.getItem("runai:mission"), framingId = storage.getItem("runai:framing");
      if (framingId) await reloadStoredFraming(framingId);
      if (!mission && missionId) await loadMission(missionId);
      render();
    } catch (error) { announce("Reprise indisponible : " + error.message + " Rechargez pour réessayer, sans nouveau lancement."); }
  }
  async function reloadStoredFraming(id) { framing = await api.request("/api/framings/" + encodeURIComponent(id)); if (framing.mission_id) await loadMission(framing.mission_id); }
  init();
})();
