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
  let journeyScripts, pendingFocus, voiceFraming, voiceMission, voiceAborted = false, voiceState = "idle";
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
    waiting_for_user: "À vous de répondre", awaiting_human: "Préparatifs terminés · à finaliser manuellement sur le site officiel",
    stopped_before_commitment: "À finaliser vous-même", completed: "Préparé",
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
    node.onclick = () => { pendingFocus = node.dataset.focusKey; action(); }; return node;
  }
  function link(parent, url, text) {
    if (!url) return;
    try {
      const parsed = new URL(url);
      if (!["https:", "http:"].includes(parsed.protocol)) return;
      const node = el("a", text || url); node.href = parsed.href;
      node.setAttribute("aria-label", (text || url) + " (nouvel onglet)");
      node.target = "_blank"; node.rel = "noopener noreferrer"; parent.append(node);
    } catch (_) { /* Une source invalide ne devient pas un lien. */ }
  }
  function announce(text) { feedback.textContent = text; feedback.className = ""; }
  function mode(value) {
    document.getElementById("mode").className = "badge" + (value === "live" ? " real" : "");
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
    const submit = button("Envoyer · " + title, () => {}, true); submit.type = "submit";
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
    const steps = screen.querySelector(".steps");
    if (mission && page === "progress" && steps?.dataset.context === agentContext() &&
        (screen.querySelector(".agent-live[open]") || screen.querySelector(".agent-history[open]"))) {
      renderAgentSteps(steps);
      screen.querySelectorAll("button").forEach(node => { node.disabled = busy; });
      pendingFocus = null;
      return;
    }
    const active = document.activeElement;
    const focusKey = pendingFocus || active?.dataset.focusKey;
    const hadFocus = pendingFocus != null || screen.contains(active);
    pendingFocus = null;
    const selection = active?.selectionStart;
    destroyView(); screen.replaceChildren();
    document.body?.classList?.toggle("dawn", !mission);
    if (mission) { mode(mission.mode); renderMission(); }
    else if (framing) { mode(framing.mode); renderFraming(); }
    else renderStart();
    if (framing?.status !== "cancelled" && mission?.status !== "cancelled") voiceControls();
    screen.querySelectorAll("input, textarea, button").forEach((node, index) => {
      node.dataset.focusKey = node.tagName === "BUTTON" ? "button:" + node.textContent : "field:" + index;
    });
    if (hadFocus) {
      const replacement = Array.from(screen.querySelectorAll("[data-focus-key]")).find((node) => node.dataset.focusKey === focusKey && !node.disabled);
      if (replacement) {
        replacement.focus();
        if (selection != null && replacement.setSelectionRange) replacement.setSelectionRange(selection, selection);
      } else {
        const heading = screen.querySelector("h1");
        if (heading) { heading.tabIndex = -1; heading.focus(); }
      }
    }
  }
  async function mutate(action, reload) {
    if (busy) return;
    let accepted = false;
    busy = true; screen.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    announce("Envoi en cours…");
    try { await action(); accepted = true; persist(); announce("Demande acceptée."); }
    catch (error) {
      if (error.status === 409 && reload) {
        try { await reload(); announce("Conversation mise à jour."); }
        catch (_) { announce("Actualisation impossible. Rechargez la page pour reprendre sans relancer."); }
      } else { announce(error.message || "Connexion indisponible. Réessayez."); feedback.className = "error"; }
    } finally { busy = false; render(); }
    return accepted;
  }
  async function reloadFraming() {
    framing = await api.request("/api/framings/" + encodeURIComponent(framing.id));
    if (framing.mission_id) await loadMission(framing.mission_id);
  }
  async function submitReply(text, options = {}) {
    if (!framing || mission) return;
    if (options.revision != null && options.revision !== framing.revision) {
      await reloadFraming(); render();
      throw new Error("Révision vocale périmée. Vérifiez le cadrage actualisé avant de répondre.");
    }
    return mutate(async () => {
      framing = await api.request("/api/framings/" + encodeURIComponent(framing.id) + "/replies", core.replyPayload(framing, text, options));
      drafts.clear();
    }, reloadFraming);
  }
  const IDEAS = ["Mon premier semi en octobre", "Un marathon au printemps, depuis Lyon", "Un trail en montagne cet été"];
  function chatField(parent, title, placeholder, onSubmit, draftKey) {
    const node = el("form", null, "ask");
    const fieldLabel = el("label", null, "ask-field");
    fieldLabel.append(el("span", title, "sr-only"));
    const input = el("input"); input.required = true; input.maxLength = 1000; input.name = "text";
    input.placeholder = placeholder; input.autocomplete = "off";
    input.value = drafts.get(draftKey) || "";
    input.oninput = () => drafts.set(draftKey, input.value);
    fieldLabel.append(input);
    const submit = button("Envoyer", () => {}, true); submit.type = "submit"; submit.className += " send";
    submit.setAttribute("aria-label", "Envoyer · " + title);
    node.append(fieldLabel, submit);
    node.onsubmit = (event) => {
      event.preventDefault();
      if (busy || !input.value.trim()) return;
      const text = input.value.trim(); input.value = ""; drafts.delete(draftKey);
      node.className += " sending"; showPending(text); onSubmit(text);
    };
    parent.append(node);
    return node;
  }
  function showPending() {
    screen.className += " thinking";
    const runner = el("div", null, "runner");
    runner.setAttribute("role", "img"); runner.setAttribute("aria-label", "RunAI réfléchit");
    const streaks = el("div", null, "runner-streaks");
    for (let i = 0; i < 4; i++) streaks.append(el("i"));
    runner.append(streaks, el("div", null, "runner-photo"), el("div", null, "runner-sheen"), el("div", null, "runner-floor"));
    const wrap = el("div", null, "thinking-box"); wrap.append(runner, el("p", "RunAI cherche pour vous…", "think"));
    const anchor = screen.querySelector(".ask");
    if (anchor?.parentNode && anchor.parentNode.insertBefore) anchor.parentNode.insertBefore(wrap, anchor); else screen.append(wrap);
  }
  function startFraming(text) {
    return mutate(async () => { framing = await api.request("/api/framings", { text, channel: "text" }); drafts.clear(); });
  }
  function renderStart() {
    screen.className = "hero";
    screen.append(el("h1", "Où voulez-vous courir ?"), el("p", "Dites-moi votre prochain objectif. Je trouve la course, le dossard, l’hôtel et le trajet, et je m’arrête avant de payer.", "hero-sub"));
    chatField(screen, "Votre objectif de course", "Un marathon au printemps, une ville, une envie…", startFraming, "start");
    const ideas = el("div", null, "ideas");
    for (const idea of IDEAS) ideas.append(button(idea, () => { showPending(); startFraming(idea); }));
    screen.append(ideas);
  }
  const voice = window.RunAIVoiceInput?.createVoiceInput({
    getRevision: () => framing?.revision ?? 0,
    onFramingReply: async ({ text, revision }) => {
      if (voiceAborted || voiceFraming !== framing?.id || voiceMission !== mission?.mission_id) throw new Error("Cette demande vocale n’est plus active.");
      let accepted;
      if (!framing && !mission && revision === 0) {
        accepted = await mutate(async () => { framing = await api.request("/api/framings", { text, channel: "voice" }); });
      } else accepted = await window.RunAIShell.submitReply(text, {
        channel: "voice", revision,
        question_id: framing?.open_questions.find(question => question.allow_free_text)?.id,
      });
      if (!accepted) throw new Error("Réponse vocale non appliquée. Vérifiez la version actuelle du cadrage.");
    },
    onAgentsCommand: async action => {
      if (voiceAborted || voiceMission !== mission?.mission_id) throw new Error("Cette commande vocale n’est plus active.");
      const accepted = await mutate(async () => {
        if (!mission) throw new Error("Aucun agent lancé.");
        mission = await api.request("/api/missions/" + encodeURIComponent(mission.mission_id) + "/" + action, {});
      }, () => loadMission(mission.mission_id));
      if (!accepted) throw new Error("Commande des agents non appliquée. Vérifiez leur état.");
    },
    view: Object.fromEntries(["pause", "play", "showChapter", "seekKm"].map(method => [method, (...args) => {
      if (!view) throw new Error("Ouvrez Explorer pour commander la caméra.");
      return view[method](...args);
    }])),
    onStateChange: state => { voiceState = state.state; if (!busy) render(); announce(state.message || ({ listening: "Microphone actif.", transcribing: "Transcription en cours…", idle: "Microphone arrêté." }[state.state] || state.state)); },
  });
  function voiceControls() {
    if (!voice) return;
    const controls = el("div", null, "question-options voice-controls");
    if (mission || voiceState !== "listening") controls.append(button("Parler", () => {
      voiceFraming = framing?.id; voiceMission = mission?.mission_id; voice.start();
    }));
    if (mission || voiceState === "listening") {
      const stop = button("Terminer l’enregistrement", () => voice.stop()); stop.className += " rec"; controls.append(stop);
    }
    (screen.querySelector(".ask") || screen).append(controls);
  }
  function slotText(name, slot) {
    const value = slot.value;
    if (value == null) return label(name) + " : sans objet";
    if (name === "distance_km" && typeof value === "number") return value + " km";
    if (name === "budget" && typeof value === "number") return value + " € max";
    if (name === "nights" && typeof value === "number") return value + (value > 1 ? " nuits" : " nuit");
    if (Array.isArray(value)) return value.map(label).join(" – ");
    if (typeof value === "object") return Object.values(value).filter((v) => v != null).map(label).join(" – ") || label(name);
    return name === "origin" ? "Depuis " + value : label(value);
  }
  function understood(parent) {
    const list = el("ul", null, "understood"); list.setAttribute("aria-label", "Ce que RunAI a compris");
    let missing = 0;
    for (const [name, slot] of Object.entries(framing.slots)) {
      if (["answered", "sourced"].includes(slot.status)) list.append(el("li", slotText(name, slot), "chip"));
      else if (slot.status !== "not_needed" && missing < 3) { missing += 1; list.append(el("li", label(name) + " ?", "chip empty")); }
    }
    if (list.children.length) parent.append(list);
  }
  function typewrite(node, text) {
    node.textContent = text;
    const motion = typeof matchMedia === "function" && !matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!motion || typeof setTimeout !== "function" || typewrite.done === text) return;
    typewrite.done = text;
    node.setAttribute("aria-label", text); node.textContent = "";
    let index = 0;
    const step = () => {
      if (!node.isConnected) return;
      index += 1; node.textContent = text.slice(0, index);
      if (index < text.length) setTimeout(step, 22);
    };
    step();
  }
  function renderFraming() {
    screen.className = "chat";
    screen.append(el("h1", "Votre course, en discutant", "sr-only"));
    const state = core.framingState(framing);
    if (state === "cancelled") {
      screen.append(el("p", "Demande annulée. Aucun agent lancé.", "say"));
      screen.append(button("Nouvelle demande", () => { framing = null; storage.removeItem("runai:framing"); render(); }, true));
      return;
    }
    understood(screen);
    const pick = framing.open_questions.find((q) => q.choices.some((c) => c.candidate_id));
    const question = framing.open_questions.find((q) => !q.choices.some((c) => c.candidate_id));
    const last = framing.turns[framing.turns.length - 1];
    const phrased = last?.role === "assistant" && last.revision === framing.revision ? last.text : null;
    const sayText = phrased || question?.text || pick?.text
      || (state === "ready_to_confirm" ? "Tout est prêt. Vérifiez le récapitulatif avant de lancer la recherche." : "Dites-m’en un peu plus sur votre projet.");
    const say = el("p", null, "say"); say.setAttribute("aria-live", "polite"); screen.append(say); typewrite(say, sayText);
    if (question) {
      const choices = el("div", null, "replies");
      for (const choice of question.choices) choices.append(button(choice.label, () => submitReply(choice.label, { channel: "buttons", question_id: question.id, choice_id: choice.id })));
      if (choices.children.length) screen.append(choices);
    } else if (pick && framing.candidates.length) {
      const list = el("div", null, "candidates");
      for (const candidate of framing.candidates) {
        const card = el("article", null, "candidate");
        card.append(el("h2", candidate.name), el("p", [candidate.city, candidate.country, candidate.race_date || "Date inconnue", candidate.distances_km.join(" / ") + " km"].join(" · "), "candidate-meta"));
        const choice = pick.choices.find((c) => c.candidate_id === candidate.id);
        if (choice) card.append(button("Choisir cette course · " + candidate.name, () => {
          card.className += " picked";
          list.children.forEach?.((other) => { if (other !== card) other.className += " dim"; });
          submitReply(choice.label, { channel: "buttons", question_id: pick.id, choice_id: choice.id });
        }, true));
        link(card, candidate.official_url || candidate.sources[0]?.url, "Source officielle");
        limitations(card, candidate.limitations); list.append(card);
      }
      screen.append(list);
      const others = el("div", null, "replies");
      for (const choice of pick.choices.filter((c) => !c.candidate_id)) others.append(button(choice.label, () => submitReply(choice.label, { channel: "buttons", question_id: pick.id, choice_id: choice.id })));
      if (others.children.length) screen.append(others);
    }
    const slots = el("details", null, "trace corrections"); slots.append(el("summary", "Modifier quelque chose"));
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
    if (state === "ready_to_confirm" && framing.summary) {
      const summary = el("section", null, "ready");
      summary.append(el("h2", framing.summary.race?.name || "Votre demande, avant lancement"));
      const lines = el("ul", null, "ready-lines");
      framing.summary.lines.forEach((line) => lines.append(el("li", line)));
      summary.append(lines);
      limitations(summary, framing.summary.limitations);
      summary.append(button("Lancer la recherche", () => mutate(async () => {
        const result = await api.request("/api/framings/" + encodeURIComponent(framing.id) + "/confirm", {
          revision: framing.summary.revision, idempotency_key: key(framing.id, framing.summary.revision),
        });
        mission = result; framing.mission_id = result.mission_id; subscribe();
      }, reloadFraming), true));
      summary.append(el("p", "Trois agents vont naviguer pour vous. Ils s’arrêtent avant tout paiement ou envoi définitif.", "hint"), slots);
      screen.append(summary);
    }
    limitations(screen, framing.limitations);
    const free = question?.allow_free_text ? question : pick?.allow_free_text ? pick : null;
    const dock = el("div", null, "dock");
    if (free) chatField(dock, "Votre réponse · " + free.text, "Répondez ou parlez…", (text) => submitReply(text, { question_id: free.id }), free.id);
    else chatField(dock, "Compléter ou corriger votre demande", state === "ready_to_confirm" ? "Une précision ? Écrivez-la ici…" : "Répondez ou parlez…", submitReply, "reply");
    screen.append(dock);
    if (state !== "ready_to_confirm") screen.append(slots);
    screen.append(button("Annuler la demande", () => mutate(async () => {
      framing = await api.request("/api/framings/" + encodeURIComponent(framing.id) + "/cancel", {});
    }, reloadFraming), false));
  }
  async function loadMission(id) {
    mission = await api.request("/api/missions/" + encodeURIComponent(id)); persist(); subscribe();
  }
  function subscribe() {
    if (events) { events.close(); events = null; }
    const terminal = () => ["awaiting_human", "completed", "cancelled", "failed"].includes(mission.status);
    if (mock || !window.EventSource || terminal()) return;
    const source = events = new EventSource("/api/missions/" + encodeURIComponent(mission.mission_id) + "/events");
    const refresh = async () => {
      try {
        const previousStatus = mission.status;
        mission = await api.request("/api/missions/" + encodeURIComponent(mission.mission_id));
        if (terminal()) {
          source.onerror = null; source.close();
          if (events === source) events = null;
        }
        if (previousStatus !== mission.status || terminal()) announce("Statut de la mission : " + label(mission.status));
        if (!busy && !screen.querySelector("input:focus, textarea:focus")) render();
      }
      catch (_) { announce("Suivi interrompu. La reconnexion ne relance pas les agents."); }
    };
    for (const name of ["message", "snapshot", "mission_status", "step", "question_opened", "question_resolved", "journey_revised", "budget_updated", "trace"]) source.addEventListener(name, refresh);
    source.onerror = () => { if (!terminal()) announce("Reconnexion au suivi en cours…"); };
  }
  function questionBlock(question) {
    const block = el("article", null, "agent-question");
    block.append(el("h2", question.text), el("p", label(question.step) + " · " + label(question.status)));
    if (question.reason) block.append(el("p", question.reason));
    if (question.status !== "open") { if (question.answer) block.append(el("p", question.answer)); return block; }
    const answer = (text) => mutate(async () => {
      mission = await api.request("/api/missions/" + encodeURIComponent(mission.mission_id) + "/questions/" + encodeURIComponent(question.question_id) + "/answer", {
        answer: text, revision: question.revision, idempotency_key: key(question.question_id, question.revision),
      }); drafts.delete(question.question_id);
    }, () => loadMission(mission.mission_id));
    const choices = el("div", null, "question-options");
    question.choices.forEach((choice) => choices.append(button(choice, () => answer(choice))));
    block.append(choices); form(block, "Votre réponse · " + question.text, answer, question.question_id);
    return block;
  }
  function agentContext() {
    return JSON.stringify([mission.mission_id, mission.status, mission.questions, mission.limitations, mission.error]);
  }
  function renderAgentSteps(steps) {
    steps.dataset.context = agentContext();
    for (const step of mission.steps) {
      let block = Array.from(steps.children).find(node => node.dataset.kind === step.kind);
      if (!block) {
        block = el("article", null, "step"); block.dataset.kind = step.kind;
        block.append(el("div", null, "agent-content")); steps.append(block);
      }
      const content = block.querySelector(".agent-content");
      const active = ["running", "paused", "waiting_for_user"].includes(step.status);
      content.replaceChildren(el("h3", label(step.kind)), el("p", label(step.status), "status"), el("p", step.summary || "En attente"));
      content.append(el("p", step.data?.last_action || "Aucune action H reçue pour cette étape.", "last-action"));
      if (step.stop_point) content.append(el("p", "Point d’arrêt : " + label(step.stop_point)));
      if (step.error) content.append(el("p", step.error));
      link(content, step.data?.manual_url || step.url, "Continuer manuellement sur le site officiel");
      if (active) link(content, step.live_view_url, "Voir l’agent en direct");
      link(content, step.agent_view_url, "Replay H");
      if (step.agent_view_url) content.append(el("p", "Le replay nécessite une connexion à votre organisation H."));
      let history = block.querySelector(".agent-history");
      if (!history) {
        history = el("details", null, "agent-history");
        history.append(el("summary", "Historique de l’agent"), el("div", null, "agent-events")); block.append(history);
      }
      const list = el("ol");
      for (const event of step.data?.history || []) {
        const item = el("li"), time = new Date(event.at);
        if (!Number.isNaN(time.getTime())) {
          const stamp = el("time", time.toLocaleString("fr-FR")); stamp.setAttribute("datetime", event.at); item.append(stamp);
        }
        item.append(el("span", event.message || event.type)); list.append(item);
      }
      history.querySelector(".agent-events").replaceChildren(list.children.length ? list : el("p", "Aucun événement reçu pour cette étape."));
      const details = el("details"); details.append(el("summary", "Détails techniques"), el("p", step.h_session_id || "Session non disponible")); content.append(details);
      let liveUrl;
      try { const url = new URL(step.live_view_url); if (url.protocol === "https:") liveUrl = url.href; } catch (_) { /* Pas de vue embarquée sans URL HTTPS. */ }
      const observation = step.data?.browser_observation;
      const hasCapture = Number.isInteger(observation?.revision) && observation.revision > 0;
      const panelKey = active && liveUrl ? liveUrl : "captures";
      let panel = block.querySelector(".agent-live");
      if (panel && (!(hasCapture || active && liveUrl) || panel.dataset.url !== panelKey)) { panel.remove(); panel = null; block.dataset.expanded = "false"; }
      if ((hasCapture || active && liveUrl) && !panel) {
        panel = el("details", null, "agent-live"); panel.dataset.url = panelKey;
        panel.append(el("summary", "Agent en direct · " + label(step.kind)));
        const enlarge = button("Agrandir", () => {
          const expanded = block.dataset.expanded !== "true";
          block.dataset.expanded = String(expanded); enlarge.textContent = expanded ? "Réduire" : "Agrandir";
        });
        panel.append(enlarge, el("p", "", "agent-page"), el("div", null, "agent-page-url"), el("p", "", "agent-capture-status"));
        if (active && liveUrl) {
          panel.append(el("p", "Si la vue ne s’affiche pas, ouvrez-la dans un onglet. Elle expire à la fin de l’exécution."));
          link(panel, liveUrl, "Ouvrir dans un onglet");
        }
        panel.ontoggle = () => {
          if (!panel.open) return;
          if (panel.dataset.screenshot && !panel.querySelector("img")) {
            const image = el("img"); image.alt = "Dernière capture du navigateur H · " + label(step.kind);
            image.onerror = () => { image.hidden = true; panel.querySelector(".agent-capture-status").textContent = "Capture indisponible. Attendez la prochaine observation ou ouvrez Replay H."; };
            image.onload = () => { image.hidden = false; };
            image.src = panel.dataset.screenshot; panel.append(image);
          }
          if (active && liveUrl && !panel.querySelector("iframe")) {
            const frame = el("iframe"); frame.src = liveUrl; frame.title = "Vue en direct de l’agent · " + label(step.kind);
            frame.setAttribute("sandbox", "allow-scripts allow-same-origin"); frame.setAttribute("referrerpolicy", "no-referrer"); panel.append(frame);
          }
        };
        block.append(panel);
      }
      if (panel && hasCapture) {
        panel.querySelector(".agent-page").textContent = observation.title || "Titre de page non renseigné";
        const pageUrl = panel.querySelector(".agent-page-url"); pageUrl.replaceChildren(); link(pageUrl, observation.url, observation.url);
        const source = "/api/missions/" + encodeURIComponent(mission.mission_id) + "/steps/" + encodeURIComponent(step.kind) + "/screenshot?v=" + observation.revision;
        if (panel.dataset.screenshot !== source) {
          panel.dataset.screenshot = source;
          panel.querySelector(".agent-capture-status").textContent = active ? "Captures H actualisées au fil des observations, pas un flux vidéo." : "Dernière capture H · étape terminée.";
          const image = panel.querySelector("img"); if (image) { image.hidden = false; image.src = source; }
          if (panel.open) panel.ontoggle();
        }
        if (!active && !panel.querySelector("img")?.hidden) panel.querySelector(".agent-capture-status").textContent = "Dernière capture H · étape terminée.";
      }
    }
  }
  function renderMission() {
    screen.className = "shell-stack";
    screen.append(el("h1", "Mon séjour"));
    const questions = mission.questions || [];
    if (questions.some((q) => q.status === "open")) {
      const priority = el("section", null, "questions"); priority.append(el("h2", "À vous de répondre"));
      questions.filter((q) => q.status === "open").forEach((q) => priority.append(questionBlock(q))); screen.append(priority);
    }
    const nav = el("nav", null, "question-options"); nav.setAttribute("aria-label", "Écrans du séjour");
    [["progress", "Préparatifs en cours"], ["stay", "Mon séjour"], ["explore", "Explorer"]].forEach(([id, title]) => {
      const item = button(title, () => { page = id; render(); });
      if (page === id) item.setAttribute("aria-current", "page");
      nav.append(item);
    });
    const statusText = mission.status === "awaiting_human" && questions.some(q => q.status === "open") ? label("waiting_for_user") : label(mission.status);
    screen.append(nav, el("h2", page === "stay" ? "Mon séjour" : page === "explore" ? "Explorer" : "Préparatifs en cours"), el("p", statusText));
    if (mission.error) screen.append(el("p", mission.error));
    if (page === "explore") { renderExplorer(); return; }
    if (page === "stay") {
      screen.append(el("p", "Séjour préparé · aucun engagement automatique."), el("h3", mission.race?.name || "Course en préparation"),
        el("p", "Date de course : " + (mission.race?.race_date || "inconnue")));
      if (framing?.summary) screen.append(el("p", framing.summary.date_range.join(" → ")));
      const budget = core.budgetText(mission.budget);
      budget.lines.forEach((line, index) => { screen.append(el("p", line)); provenance(screen, mission.budget.lines[index].money); });
      screen.append(el("p", budget.total, "total"), el("p", budget.cap));
      if (mission.journey_revision != null) {
        const exports = el("nav"); exports.setAttribute("aria-label", "Exporter ce séjour");
        for (const format of ["html", "pdf", "ics"]) link(exports,
          new URL("/api/missions/" + encodeURIComponent(mission.mission_id) + "/recap." + format + "?revision=" + mission.journey_revision, location.href).href,
          "Exporter " + format.toUpperCase());
        screen.append(exports);
      }
      for (const id of mission.budget?.missing_line_ids || []) {
        if (!mission.budget.lines.some((line) => line.id === id)) screen.append(el("p", "Poste manquant : Prix inconnu"));
      }
    }
    const steps = el("div", null, "steps");
    renderAgentSteps(steps);
    screen.append(steps); limitations(screen, mission.limitations);
    questions.filter((q) => q.status !== "open").forEach((q) => screen.append(questionBlock(q)));
    if (mission.status !== "cancelled") screen.append(button("Annuler les préparatifs", () => mutate(async () => {
      mission = await api.request("/api/missions/" + encodeURIComponent(mission.mission_id) + "/cancel", {});
      if (events) events.close();
    }, () => loadMission(mission.mission_id))));
  }
  async function renderExplorer() {
    const container = el("div", null, "journey-map"); container.setAttribute("aria-label", "Carte du séjour"); container.setAttribute("role", "region");
    const fallback = el("section", null, "shell-stack");
    screen.append(container, fallback);
    try {
      plan = await api.request("/api/missions/" + encodeURIComponent(mission.mission_id) + "/journey");
      await loadJourneyScripts();
      if (page !== "explore" || !container.isConnected) return;
      const errors = window.RunAIJourneyContract?.validateJourneyPlan(plan) || [];
      if (errors.length) throw new Error("Le parcours reçu est invalide. Réessayez après actualisation.");
      mode(plan.mode);
      const controls = el("div", null, "question-options"); screen.insertBefore(controls, container);
      view = window.RunAIJourneyView.createJourneyView(container, { reducedMotion: matchMedia("(prefers-reduced-motion: reduce)").matches,
        timelineContainer: fallback, errorTarget: screen,
        onEvent: (name, detail) => {
          window.dispatchEvent(new CustomEvent("runai:shell-journey", { detail: { name, ...detail } }));
          if (name === window.RunAIJourneyContract.MAP_EVENTS.error && detail.fatal !== false) announce("Carte indisponible. Le parcours reste disponible dans la timeline.");
        },
      });
      view.setPlan(plan);
      plan.chapters.forEach((chapter) => controls.append(button(chapter.label, () => view?.showChapter(chapter.id))));
      if (!matchMedia("(prefers-reduced-motion: reduce)").matches) controls.append(button("Lecture", () => view?.play()));
      controls.append(button("Pause", () => view?.pause()));
    } catch (error) {
      fallback.append(el("p", error.message), button("Réessayer", render));
    }
  }
  window.RunAIShell = { api, submitReply };
  window.addEventListener("pagehide", () => { voiceAborted = true; voice?.stop(); destroyView(); if (events) events.close(); });
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
