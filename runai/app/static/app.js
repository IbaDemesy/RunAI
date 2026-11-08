/* Shell V2: every mutation goes through this replaceable API. */
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
      if (!response.ok) { const error = new Error("The request failed (" + response.status + "). Try again."); error.status = response.status; throw error; }
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
    registration: "Registration", accommodation: "Hotel", transport: "Transport",
    pending: "Waiting", searching: "Searching", running: "Running", paused: "Paused",
    waiting_for_user: "Your turn to answer", awaiting_human: "Preparation done · finish manually on the official site",
    stopped_before_commitment: "Finish it yourself", completed: "Prepared",
    failed: "Failed", cancelled: "Cancelled", open: "Open", answered: "Answer accepted",
    expired: "Expired", refused: "Refused", payment: "Payment", account: "Account creation",
    consent: "Consent", verified: "Verified", estimated: "Estimated", illustrative: "Illustrative",
    unknown: "Unknown", fixture: "Demo", live: "Live", replay: "Replay",
    flight: "Flight", train: "Train", car: "Car", bus: "Bus", local: "Local transport",
    city: "City", race: "Race", edition: "Edition", race_date: "Race date",
    date_window: "Period", distance_km: "Distance (km)", origin: "Origin", budget: "Budget",
    nights: "Nights", transport_mode: "Transport mode", preferences: "Preferences",
  };
  const label = (value) => labels[value] || value || "unknown";
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
      node.setAttribute("aria-label", (text || url) + " (new tab)");
      node.target = "_blank"; node.rel = "noopener noreferrer"; parent.append(node);
    } catch (_) { /* An invalid source does not become a link. */ }
  }
  function announce(text, quiet) { feedback.textContent = text; feedback.className = quiet ? "quiet" : ""; }
  function mode(value) {
    document.getElementById("mode").className = "badge" + (value === "live" ? " real" : "");
    document.getElementById("mode").textContent = ({ live: "Live · live", demo: "Demo · demo", replay: "Replay · replay" })[value] || "Mode not verified";
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
    const submit = button("Send · " + title, () => {}, true); submit.type = "submit";
    node.append(fieldLabel, submit);
    node.onsubmit = (event) => { event.preventDefault(); if (!busy && input.value.trim()) onSubmit(input.value.trim()); };
    parent.append(node);
  }
  function limitations(parent, values = []) {
    for (const item of values) {
      const row = el("p", item.message, "hint"); link(row, item.manual_url, " Open the official site"); parent.append(row);
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
    window.RunAIPartners?.decorate(screen, { framing, mission, voiceState });
  }
  async function mutate(action, reload) {
    if (busy) return;
    let accepted = false;
    busy = true; screen.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    announce("Sending…", true);
    try { await action(); accepted = true; persist(); announce("Request accepted.", true); }
    catch (error) {
      if (error.status === 409 && reload) {
        try { await reload(); announce("Conversation updated.", true); }
        catch (_) { announce("Unable to refresh. Reload the page to resume without starting again."); }
      } else { announce(error.message || "Connection unavailable. Try again."); feedback.className = "error"; }
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
      throw new Error("Voice revision expired. Check the updated request before answering.");
    }
    return mutate(async () => {
      framing = await api.request("/api/framings/" + encodeURIComponent(framing.id) + "/replies", core.replyPayload(framing, text, options));
      drafts.clear();
    }, reloadFraming);
  }
  const IDEAS = ["My first half marathon in October", "A spring marathon, leaving from Lyon", "A mountain trail this summer"];
  function chatField(parent, title, placeholder, onSubmit, draftKey) {
    const node = el("form", null, "ask");
    const fieldLabel = el("label", null, "ask-field");
    fieldLabel.append(el("span", title, "sr-only"));
    const input = el("input"); input.required = true; input.maxLength = 1000; input.name = "text";
    input.placeholder = placeholder; input.autocomplete = "off";
    input.value = drafts.get(draftKey) || "";
    input.oninput = () => drafts.set(draftKey, input.value);
    fieldLabel.append(input);
    const submit = button("Send", () => {}, true); submit.type = "submit"; submit.className += " send";
    submit.setAttribute("aria-label", "Send · " + title);
    node.append(fieldLabel, submit);
    node.onsubmit = (event) => {
      event.preventDefault();
      if (busy || !input.value.trim()) return;
      const text = input.value.trim(); input.value = "";
      node.className += " sending"; showPending(text); onSubmit(text);
    };
    parent.append(node);
    return node;
  }
  function showPending() {
    screen.className += " thinking";
    const runner = el("div", null, "runner");
    runner.setAttribute("role", "img"); runner.setAttribute("aria-label", "RunAI is thinking");
    const streaks = el("div", null, "runner-streaks");
    for (let i = 0; i < 4; i++) streaks.append(el("i"));
    runner.append(streaks, el("div", null, "runner-photo"), el("div", null, "runner-sheen"), el("div", null, "runner-floor"));
    const wrap = el("div", null, "thinking-box"); wrap.append(runner, el("p", "RunAI is searching for you…", "think"));
    const anchor = screen.querySelector(".ask");
    if (anchor?.parentNode && anchor.parentNode.insertBefore) anchor.parentNode.insertBefore(wrap, anchor); else screen.append(wrap);
  }
  function startFraming(text) {
    return mutate(async () => { framing = await api.request("/api/framings", { text, channel: "text" }); drafts.clear(); });
  }
  function renderStart() {
    screen.className = "hero";
    screen.append(el("h1", "Where do you want to run?"), el("p", "Tell me your next goal. I find the race, the bib, the hotel and the trip, and I stop before paying.", "hero-sub"));
    chatField(screen, "Your running goal", "A spring marathon, a city, an idea…", startFraming, "start");
    const ideas = el("div", null, "ideas");
    for (const idea of IDEAS) ideas.append(button(idea, () => { showPending(); startFraming(idea); }));
    screen.append(ideas);
  }
  const voice = window.RunAIVoiceInput?.createVoiceInput({
    getRevision: () => framing?.revision ?? 0,
    onFramingReply: async ({ text, revision }) => {
      if (voiceAborted || voiceFraming !== framing?.id || voiceMission !== mission?.mission_id) throw new Error("This voice request is no longer active.");
      let accepted;
      if (!framing && !mission && revision === 0) {
        accepted = await mutate(async () => { framing = await api.request("/api/framings", { text, channel: "voice" }); });
      } else accepted = await window.RunAIShell.submitReply(text, {
        channel: "voice", revision,
        question_id: framing?.open_questions.find(question => question.allow_free_text)?.id,
      });
      if (!accepted) throw new Error("Voice answer not applied. Check the current request.");
    },
    onAgentsCommand: async action => {
      if (voiceAborted || voiceMission !== mission?.mission_id) throw new Error("This voice command is no longer active.");
      const accepted = await mutate(async () => {
        if (!mission) throw new Error("No agents started.");
        mission = await api.request("/api/missions/" + encodeURIComponent(mission.mission_id) + "/" + action, {});
      }, () => loadMission(mission.mission_id));
      if (!accepted) throw new Error("Agent command not applied. Check their status.");
    },
    view: Object.fromEntries(["pause", "play", "showChapter", "seekKm"].map(method => [method, (...args) => {
      if (!view) throw new Error("Open Explore to control the camera.");
      return view[method](...args);
    }])),
    onStateChange: state => { voiceState = state.state; if (!busy) render(); announce(state.message || ({ listening: "Microphone on.", transcribing: "Transcribing…", idle: "Microphone off." }[state.state] || state.state), !state.message); },
  });
  function voiceControls() {
    if (!voice) return;
    const state = voice.getState?.() || { state: voiceState };
    const controls = el("div", null, "question-options voice-controls");
    if (mission || voiceState !== "listening") controls.append(button("Speak", () => {
      voiceFraming = framing?.id; voiceMission = mission?.mission_id; voice.start();
    }));
    if (mission || voiceState === "listening") {
      const stop = button("Stop recording", () => voice.stop()); stop.className += " rec"; controls.append(stop);
    }
    if (state.state === "listening" && state.partial) {
      const partial = el("p", state.partial, "voice-partial"); partial.setAttribute("aria-live", "polite"); controls.append(partial);
    }
    const voiceMode = mission?.mode || framing?.mode;
    const voiceLabel = voiceMode === "demo" ? "Demo voice" : voiceMode === "replay" ? "Recorded voice" : "Voice input";
    const badge = el("p", voiceLabel, "partner-badge");
    badge.setAttribute("data-partner", "voice"); controls.append(badge);
    (screen.querySelector(".ask") || screen).append(controls);
  }
  function slotText(name, slot) {
    const value = slot.value;
    if (value == null) return label(name) + " : not applicable";
    if (name === "distance_km" && typeof value === "number") return value + " km";
    if (name === "budget" && typeof value === "number") return value + " € max";
    if (name === "nights" && typeof value === "number") return value + (value > 1 ? " nights" : " night");
    if (Array.isArray(value)) return value.map(label).join(" – ");
    if (typeof value === "object") return Object.values(value).filter((v) => v != null).map(label).join(" – ") || label(name);
    return name === "origin" ? "From " + value : label(value);
  }
  function understood(parent) {
    const list = el("ul", null, "understood"); list.setAttribute("aria-label", "What RunAI understood");
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
  function stepper() {
    const nav = el("nav", null, "stepper"); nav.setAttribute("aria-label", "Progress");
    const current = core.journeyStage(framing, mission), list = el("ol");
    core.STAGES.forEach((title, index) => {
      const item = el("li", null, index < current ? "done" : index === current ? "current" : "todo");
      if (index === current) item.setAttribute("aria-current", "step");
      item.append(el("span", String(index + 1), "n"), el("span", title)); list.append(item);
    });
    nav.append(list); return nav;
  }
  function renderFraming() {
    screen.className = "chat";
    screen.append(el("h1", "Plan your race through conversation", "sr-only"));
    screen.append(stepper());
    const state = core.framingState(framing);
    if (state === "cancelled") {
      screen.append(el("p", "Request cancelled. No agents started.", "say"));
      screen.append(button("New request", () => { framing = null; storage.removeItem("runai:framing"); render(); }, true));
      return;
    }
    understood(screen);
    const pick = framing.open_questions.find((q) => q.choices.some((c) => c.candidate_id));
    const question = framing.open_questions.find((q) => !q.choices.some((c) => c.candidate_id));
    const last = framing.turns[framing.turns.length - 1];
    const phrased = last?.role === "assistant" && last.revision === framing.revision ? last.text : null;
    const sayText = phrased || question?.text || pick?.text
      || (state === "ready_to_confirm" ? "Everything is ready. Check the summary before starting the search." : "Tell me a little more about your plans.");
    const say = el("p", null, "say"); say.setAttribute("aria-live", "polite"); screen.append(say); typewrite(say, sayText);
    if (question) {
      const choices = el("div", null, "replies");
      for (const choice of question.choices) choices.append(button(choice.label, () => submitReply(choice.label, { channel: "buttons", question_id: question.id, choice_id: choice.id })));
      if (choices.children.length) screen.append(choices);
    } else if (pick && framing.candidates.length) {
      const list = el("div", null, "candidates");
      for (const candidate of framing.candidates) {
        const card = el("article", null, "candidate");
        card.append(el("h2", candidate.name), el("p", [candidate.city, candidate.country, candidate.race_date || "Date unknown", candidate.distances_km.join(" / ") + " km"].join(" · "), "candidate-meta"));
        const choice = pick.choices.find((c) => c.candidate_id === candidate.id);
        if (choice) card.append(button("Choose this race · " + candidate.name, () => {
          card.className += " picked";
          list.children.forEach?.((other) => { if (other !== card) other.className += " dim"; });
          submitReply(choice.label, { channel: "buttons", question_id: pick.id, choice_id: choice.id });
        }, true));
        link(card, candidate.official_url || candidate.sources[0]?.url, "Official source");
        limitations(card, candidate.limitations); list.append(card);
      }
      screen.append(list);
      const others = el("div", null, "replies");
      for (const choice of pick.choices.filter((c) => !c.candidate_id)) others.append(button(choice.label, () => submitReply(choice.label, { channel: "buttons", question_id: pick.id, choice_id: choice.id })));
      if (others.children.length) screen.append(others);
    }
    const slots = el("details", null, "trace corrections"); slots.append(el("summary", "Change something"));
    for (const [name, slot] of Object.entries(framing.slots)) {
      const known = ["answered", "sourced", "not_needed"].includes(slot.status);
      const row = el("div", null, "slot-row");
      row.append(el("p", label(name) + " : " + (known ? (slot.value == null ? "Not applicable" : typeof slot.value === "object" ? JSON.stringify(slot.value) : label(slot.value)) : "unknown")));
      row.append(button("Correct · " + label(name), () => {
        const editor = el("div"); row.append(editor);
        form(editor, "New value: " + label(name), (text) => submitReply(text, { corrections: { [name]: text } }), "slot:" + name);
        editor.querySelector("input").focus();
      }));
      slots.append(row);
    }
    if (state === "ready_to_confirm" && framing.summary) {
      const summary = el("section", null, "ready");
      summary.append(el("h2", framing.summary.race?.name || "Your request, before starting"));
      const lines = el("ul", null, "ready-lines");
      framing.summary.lines.forEach((line) => lines.append(el("li", line)));
      summary.append(lines);
      limitations(summary, framing.summary.limitations);
      summary.append(button("Start the search", () => mutate(async () => {
        const result = await api.request("/api/framings/" + encodeURIComponent(framing.id) + "/confirm", {
          revision: framing.summary.revision, idempotency_key: key(framing.id, framing.summary.revision),
        });
        mission = result; framing.mission_id = result.mission_id; subscribe();
      }, reloadFraming), true));
      summary.append(el("p", "Three agents will browse for you. They stop before any payment or final submission.", "hint"), slots);
      screen.append(summary);
    }
    limitations(screen, framing.limitations);
    const free = question?.allow_free_text ? question : pick?.allow_free_text ? pick : null;
    const dock = el("div", null, "dock");
    if (free) chatField(dock, "Your answer · " + free.text, "Type or speak your answer…", (text) => submitReply(text, { question_id: free.id }), free.id);
    else chatField(dock, "Add to or correct your request", state === "ready_to_confirm" ? "Anything to add? Write it here…" : "Type or speak your answer…", submitReply, "reply");
    screen.append(dock);
    if (state !== "ready_to_confirm") screen.append(slots);
    screen.append(button("Cancel request", () => mutate(async () => {
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
        if (previousStatus !== mission.status || terminal()) announce("Mission status: " + label(mission.status));
        if (!busy && !screen.querySelector("input:focus, textarea:focus")) render();
      }
      catch (_) { announce("Updates interrupted. Reconnecting does not restart the agents."); }
    };
    for (const name of ["message", "snapshot", "mission_status", "step", "question_opened", "question_resolved", "journey_revised", "budget_updated", "trace"]) source.addEventListener(name, refresh);
    source.onerror = () => { if (!terminal()) announce("Reconnecting to updates…"); };
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
    block.append(choices); form(block, "Your answer · " + question.text, answer, question.question_id);
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
      content.replaceChildren(el("h3", label(step.kind)), el("p", label(step.status), "status"), el("p", step.summary || "Waiting"));
      content.append(el("p", step.data?.last_action || "No H action received for this step.", "last-action"));
      if (step.stop_point) content.append(el("p", "Stop point: " + label(step.stop_point)));
      if (step.error) content.append(el("p", step.error));
      link(content, step.data?.manual_url || step.url, "Continue manually on the official site");
      if (active) link(content, step.live_view_url, "Watch the agent live");
      link(content, step.agent_view_url, "Replay H");
      if (step.agent_view_url) content.append(el("p", "Replay requires signing in to your H organization."));
      let history = block.querySelector(".agent-history");
      if (!history) {
        history = el("details", null, "agent-history");
        history.append(el("summary", "Agent history"), el("div", null, "agent-events")); block.append(history);
      }
      const list = el("ol");
      for (const event of step.data?.history || []) {
        const item = el("li"), time = new Date(event.at);
        if (!Number.isNaN(time.getTime())) {
          const stamp = el("time", time.toLocaleString("en-GB")); stamp.setAttribute("datetime", event.at); item.append(stamp);
        }
        item.append(el("span", event.message || event.type)); list.append(item);
      }
      history.querySelector(".agent-events").replaceChildren(list.children.length ? list : el("p", "No events received for this step."));
      const details = el("details"); details.append(el("summary", "Technical details"), el("p", step.h_session_id || "Session unavailable")); content.append(details);
      let liveUrl;
      try { const url = new URL(step.live_view_url, location.href); if (url.protocol === "https:" || url.origin === location.origin) liveUrl = url.href; } catch (_) { /* No embedded view without an HTTPS or same-origin URL. */ }
      const observation = step.data?.browser_observation;
      const hasCapture = Number.isInteger(observation?.revision) && observation.revision > 0;
      const panelKey = active && liveUrl ? liveUrl : "captures";
      let panel = block.querySelector(".agent-live");
      if (panel && (!(hasCapture || active && liveUrl) || panel.dataset.url !== panelKey)) { panel.remove(); panel = null; block.dataset.expanded = "false"; }
      if ((hasCapture || active && liveUrl) && !panel) {
        panel = el("details", null, "agent-live"); panel.dataset.url = panelKey;
        panel.append(el("summary", "Live agent · " + label(step.kind)));
        const enlarge = button("Enlarge", () => {
          const expanded = block.dataset.expanded !== "true";
          block.dataset.expanded = String(expanded); enlarge.textContent = expanded ? "Shrink" : "Enlarge";
        });
        panel.append(enlarge, el("p", "", "agent-page"), el("div", null, "agent-page-url"), el("p", "", "agent-capture-status"));
        if (active && liveUrl) {
          panel.append(el("p", "If the view does not appear, open it in a tab. It expires when the run ends."));
          link(panel, liveUrl, "Open in a tab");
        }
        panel.ontoggle = () => {
          if (!panel.open) return;
          if (panel.dataset.screenshot && !panel.querySelector("img")) {
            const image = el("img"); image.alt = "Latest H browser capture · " + label(step.kind);
            image.onerror = () => { image.hidden = true; panel.querySelector(".agent-capture-status").textContent = "Capture unavailable. Wait for the next observation or open H Replay."; };
            image.onload = () => { image.hidden = false; };
            image.src = panel.dataset.screenshot; panel.append(image);
          }
          if (active && liveUrl && !panel.querySelector("iframe")) {
            const frame = el("iframe"); frame.src = liveUrl; frame.title = "Live agent view · " + label(step.kind);
            frame.setAttribute("sandbox", "allow-scripts allow-same-origin"); frame.setAttribute("referrerpolicy", "no-referrer"); panel.append(frame);
          }
        };
        block.append(panel);
        if (active) { panel.open = true; panel.ontoggle(); }
      }
      if (panel && hasCapture) {
        panel.querySelector(".agent-page").textContent = observation.title || "Page title unavailable";
        const pageUrl = panel.querySelector(".agent-page-url"); pageUrl.replaceChildren(); link(pageUrl, observation.url, observation.url);
        const source = "/api/missions/" + encodeURIComponent(mission.mission_id) + "/steps/" + encodeURIComponent(step.kind) + "/screenshot?v=" + observation.revision;
        if (panel.dataset.screenshot !== source) {
          panel.dataset.screenshot = source;
          panel.querySelector(".agent-capture-status").textContent = active ? "H captures update with observations; this is not a video stream." : "Latest H capture · step finished.";
          const image = panel.querySelector("img"); if (image) { image.hidden = false; image.src = source; }
          if (panel.open) panel.ontoggle();
        }
        if (!active && !panel.querySelector("img")?.hidden) panel.querySelector(".agent-capture-status").textContent = "Latest H capture · step finished.";
      }
    }
  }
  function renderMission() {
    screen.className = "shell-stack";
    screen.append(el("h1", "My trip"));
    screen.append(stepper());
    const questions = mission.questions || [];
    if (questions.some((q) => q.status === "open")) {
      const priority = el("section", null, "questions"); priority.append(el("h2", "Your turn to answer"));
      questions.filter((q) => q.status === "open").forEach((q) => priority.append(questionBlock(q))); screen.append(priority);
    }
    const nav = el("nav", null, "question-options"); nav.setAttribute("aria-label", "Trip screens");
    [["progress", "Preparation in progress"], ["stay", "My trip"], ["explore", "Explore"]].forEach(([id, title]) => {
      const item = button(title, () => { page = id; render(); });
      if (page === id) item.setAttribute("aria-current", "page");
      nav.append(item);
    });
    const statusText = mission.status === "awaiting_human" && questions.some(q => q.status === "open") ? label("waiting_for_user") : label(mission.status);
    screen.append(nav, el("h2", page === "stay" ? "My trip" : page === "explore" ? "Explore" : "Preparation in progress"), el("p", statusText));
    if (mission.error) screen.append(el("p", mission.error));
    if (page === "explore") { renderExplorer(); return; }
    if (page === "stay") {
      screen.append(el("p", "Trip prepared · nothing committed automatically"), el("h3", mission.race?.name || "Race being prepared"),
        el("p", "Race date : " + (mission.race?.race_date || "unknown")));
      if (framing?.summary) screen.append(el("p", framing.summary.date_range.join(" → ")));
      const budget = core.budgetText(mission.budget);
      budget.lines.forEach((line, index) => { screen.append(el("p", line)); provenance(screen, mission.budget.lines[index].money); });
      screen.append(el("p", budget.total, "total"), el("p", budget.cap));
      if (mission.journey_revision != null) {
        const exports = el("nav"); exports.setAttribute("aria-label", "Export this trip");
        for (const format of ["html", "pdf", "ics"]) link(exports,
          new URL("/api/missions/" + encodeURIComponent(mission.mission_id) + "/recap." + format + "?revision=" + mission.journey_revision, location.href).href,
          "Export " + format.toUpperCase());
        screen.append(exports);
      }
      for (const id of mission.budget?.missing_line_ids || []) {
        if (!mission.budget.lines.some((line) => line.id === id)) screen.append(el("p", "Missing item: Price unknown"));
      }
    }
    const steps = el("div", null, "steps");
    renderAgentSteps(steps);
    screen.append(steps); limitations(screen, mission.limitations);
    questions.filter((q) => q.status !== "open").forEach((q) => screen.append(questionBlock(q)));
    if (mission.status !== "cancelled") screen.append(button("Cancel preparation", () => mutate(async () => {
      mission = await api.request("/api/missions/" + encodeURIComponent(mission.mission_id) + "/cancel", {});
      if (events) events.close();
    }, () => loadMission(mission.mission_id))));
  }
  async function renderExplorer() {
    const container = el("div", null, "journey-map"); container.setAttribute("aria-label", "Trip map"); container.setAttribute("role", "region");
    const fallback = el("section", null, "shell-stack");
    screen.append(container, fallback);
    try {
      plan = await api.request("/api/missions/" + encodeURIComponent(mission.mission_id) + "/journey");
      await loadJourneyScripts();
      if (page !== "explore" || !container.isConnected) return;
      const errors = window.RunAIJourneyContract?.validateJourneyPlan(plan) || [];
      if (errors.length) throw new Error("The route received is invalid. Refresh and try again.");
      mode(plan.mode);
      const controls = el("div", null, "question-options"); screen.insertBefore(controls, container);
      view = window.RunAIJourneyView.createJourneyView(container, { reducedMotion: matchMedia("(prefers-reduced-motion: reduce)").matches,
        timelineContainer: fallback, errorTarget: screen,
        onEvent: (name, detail) => {
          window.dispatchEvent(new CustomEvent("runai:shell-journey", { detail: { name, ...detail } }));
          if (name === window.RunAIJourneyContract.MAP_EVENTS.error && detail.fatal !== false) announce("Map unavailable. The route is still available in the timeline.");
        },
      });
      view.setPlan(plan);
      plan.chapters.forEach((chapter) => controls.append(button(chapter.label, () => view?.showChapter(chapter.id))));
      if (!matchMedia("(prefers-reduced-motion: reduce)").matches) controls.append(button("Play", () => view?.play()));
      controls.append(button("Pause", () => view?.pause()));
    } catch (error) {
      fallback.append(el("p", error.message), button("Try again", render));
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
        catch (_) { mode(null); announce("Mode unavailable. Check your connection before preparing your request."); }
      }
      const missionId = storage.getItem("runai:mission"), framingId = storage.getItem("runai:framing");
      if (framingId) await reloadStoredFraming(framingId);
      if (!mission && missionId) await loadMission(missionId);
      render();
    } catch (error) { announce("Unable to resume: " + error.message + " Reload to try again without starting again."); }
  }
  async function reloadStoredFraming(id) { framing = await api.request("/api/framings/" + encodeURIComponent(id)); if (framing.mission_id) await loadMission(framing.mission_id); }
  init();
})();
