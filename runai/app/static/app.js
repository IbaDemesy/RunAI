const STATUS_LABELS = {
  pending: "En attente",
  running: "En cours",
  paused: "En pause",
  waiting_for_user: "En attente de votre réponse",
  stopped_before_commitment: "Arrêté avant engagement",
  completed: "Terminé",
  failed: "Échec",
};
const MISSION_LABELS = {
  searching: "recherche de la course",
  running: "agents en cours",
  awaiting_human: "à vous de jouer",
  completed: "terminée",
  failed: "échec",
};
const STOP_LABELS = {
  payment: "Paiement",
  account_creation: "Création de compte",
  health_declaration: "Déclaration de santé",
  consent: "Règlement / consentement",
  submission: "Soumission définitive",
};
const TERMINAL = new Set(["awaiting_human", "completed", "failed"]);

const $ = (selector, root = document) => root.querySelector(selector);
let mission = null;
let source = null;
let simulated = false;
let ticker = null;
let lastEventAt = NaN;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || response.statusText);
  }
  return response.json();
}

function renderRace(race) {
  $("#race-name").textContent = race ? race.name : "Recherche de la course…";
  const facts = $("#race-facts");
  facts.replaceChildren();
  $("#race-sources").replaceChildren();
  if (!race) return;
  const rows = [
    ["Ville", `${race.city} (${race.country})`],
    ["Date", race.race_date && `${race.race_date}${race.start_time ? " · " + race.start_time : ""}`],
    ["Distance", race.distance_km && `${race.distance_km} km`],
    ["Départ", race.start_location],
    ["Retrait du dossard", race.bib_pickup],
  ];
  for (const [label, value] of rows) {
    if (!value) continue;
    const fact = element("div");
    fact.append(element("dt", label), element("dd", value));
    facts.append(fact);
  }
  for (const item of race.sources) {
    const li = element("li");
    const link = element("a", item.title || item.url);
    link.href = item.url;
    link.target = "_blank";
    link.rel = "noopener";
    li.append("Source : ", link);
    $("#race-sources").append(li);
  }
}

function stepCard(step) {
  let card = document.getElementById(`step-${step.kind}`);
  if (!card) {
    card = $("#step-template").content.firstElementChild.cloneNode(true);
    card.id = `step-${step.kind}`;
    $(".pause", card).addEventListener("click", () => control(step.kind, "pause"));
    $(".resume", card).addEventListener("click", () => control(step.kind, "resume"));
    $(".message", card).addEventListener("submit", (event) => {
      event.preventDefault();
      const input = event.target.elements.text;
      if (!input.value.trim()) return;
      control(step.kind, "message", { text: input.value.trim() }).then(() => (input.value = ""));
    });
    $("#steps").append(card);
  }
  return card;
}

function renderQuestions(step, questions) {
  const container = $(".questions", document.getElementById(`step-${step.kind}`));
  const answers = new Map(
    [...container.querySelectorAll(".answer-form")].map((form) => [
      form.dataset.questionId,
      $("input", form).value,
    ]),
  );
  container.replaceChildren();
  const items = questions.filter((question) => question.kind === step.kind);
  container.classList.toggle("hidden", items.length === 0);
  for (const question of items) {
    const item = element("section", null, question.answer ? "question-history" : "agent-question");
    item.append(element("p", question.question, "question-text"));
    if (question.answer) {
      item.append(element("p", `Réponse : ${question.answer}`, "question-answer"));
      container.append(item);
      continue;
    }
    const options = element("div", null, "question-options");
    for (const option of question.options || []) {
      const button = element("button", option);
      button.type = "button";
      button.addEventListener("click", () => submitAnswer(question.id, option, item));
      options.append(button);
    }
    item.append(options);
    const form = element("form", null, "row answer-form");
    form.dataset.questionId = question.id;
    const input = element("input");
    input.name = "answer";
    input.value = answers.get(question.id) || "";
    input.maxLength = 500;
    input.placeholder = "Votre réponse";
    input.autocomplete = "off";
    const send = element("button", "Envoyer");
    send.type = "submit";
    form.append(input, send);
    const feedback = element("p", null, "question-feedback muted");
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      submitAnswer(question.id, input.value.trim(), item);
    });
    item.append(form, feedback);
    container.append(item);
  }
}

function renderStep(step) {
  const card = stepCard(step);
  card.dataset.status = step.status;
  $(".step-label", card).textContent = step.label;
  const status = $(".status", card);
  status.textContent = STATUS_LABELS[step.status] || step.status;
  status.className = `status status-${step.status}`;
  $(".last-action", card).textContent = step.data.last_action || STEP_IDLE_TEXT[step.status] || "";
  $(".current-url", card).textContent = step.data.current_url || "";
  const liveUrl = step.live_view_url || step.data.live_view_path;
  const frame = $(".live-frame", card);
  const link = $(".live-link", card);
  $(".live", card).classList.toggle("hidden", !liveUrl);
  if (liveUrl && link.getAttribute("href") !== liveUrl) {
    link.href = liveUrl;
    frame.src = liveUrl;
  }
  const summary = [step.summary, step.error && `Erreur : ${step.error}`].filter(Boolean).join(" ");
  $(".summary", card).textContent = summary;
  renderQuestions(step, mission.questions || []);
  const started = Boolean(step.h_session_id);
  const active = started && (step.status === "running" || step.status === "paused");
  $(".pause", card).disabled = !started || step.status !== "running";
  $(".resume", card).disabled = !started || step.status !== "paused";
  $(".message", card).classList.toggle("hidden", !active);
}

const STEP_IDLE_TEXT = {
  pending: "Agent pas encore lancé",
  running: "L'agent navigue sur le site…",
  paused: "Agent en pause",
};

function formatElapsed(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = String(total % 60).padStart(2, "0");
  return minutes ? `${minutes} min ${seconds} s` : `${total} s`;
}

function activityText(data) {
  if (data.status === "searching") return ["busy", "Recherche de la course sur le web…"];
  if (data.status === "failed") return ["failed", "La mission a échoué"];
  if (TERMINAL.has(data.status)) return ["done", "Les agents ont fini : à vous de signer"];
  const waiting = data.steps.filter((step) => step.status === "waiting_for_user").length;
  if (waiting) return ["waiting", waiting > 1 ? `${waiting} agents attendent votre réponse` : "Un agent attend votre réponse"];
  const running = data.steps.filter((step) => step.status === "running").length;
  if (running) return ["busy", running > 1 ? `${running} agents naviguent pour vous…` : "Un agent navigue pour vous…"];
  return ["busy", "Les agents se mettent en route…"];
}

function renderActivity(data) {
  const [state, text] = activityText(data);
  const box = $("#activity");
  box.dataset.state = state;
  $("#activity-text").textContent = text;
  const started = Date.parse(data.created_at);
  const tick = () => ($("#activity-elapsed").textContent = Number.isNaN(started) ? "" : formatElapsed(Date.now() - started));
  clearInterval(ticker);
  ticker = null;
  if (TERMINAL.has(data.status)) {
    const ended = Number.isNaN(lastEventAt) ? Date.now() : lastEventAt;
    $("#activity-elapsed").textContent = Number.isNaN(started) || Number.isNaN(ended) ? "" : `en ${formatElapsed(ended - started)}`;
    return;
  }
  tick();
  ticker = setInterval(tick, 1000);
}

function renderPortal(steps) {
  const stopped = steps.filter((step) => step.status === "stopped_before_commitment");
  const container = $("#portal-items");
  container.replaceChildren();
  if (!stopped.length) {
    container.append(element("p", "Les agents travaillent encore…", "muted"));
    $("#portal-total").textContent = "";
    return;
  }
  for (const step of stopped) {
    const item = element("div", null, "portal-item");
    const head = element("div", null, "portal-head");
    head.append(element("strong", step.label), element("span", `Arrêt : ${STOP_LABELS[step.stop_point] || "avant engagement"}`, "stop"));
    if (step.price_eur !== null) head.append(element("span", `${step.price_eur.toFixed(2)} €`, "price"));
    item.append(head, element("p", step.summary || ""), element("p", `À faire : ${step.human_action}`, "todo"));
    if (step.url) {
      const link = element("a", "Ouvrir la page où l'agent s'est arrêté ↗");
      link.href = step.url;
      link.target = "_blank";
      link.rel = "noopener";
      item.append(link);
    }
    container.append(item);
  }
  const total = stopped.reduce((sum, step) => sum + (step.price_eur || 0), 0);
  const waiting = steps.filter((step) => ["pending", "running", "paused", "waiting_for_user"].includes(step.status)).length;
  $("#portal-total").textContent =
    `Total estimé à payer vous-même : ${total.toFixed(2)} €` + (waiting ? ` · ${waiting} agent(s) encore en cours` : "");
}

function appendEvent(event) {
  const item = element("li");
  const at = Date.parse(event.at);
  if (!(at <= lastEventAt)) lastEventAt = at;
  const time = new Date(event.at).toLocaleTimeString("fr-FR");
  item.append(element("time", time), element("span", event.source, `source source-${event.source.split(":")[0]}`), element("span", event.message || event.type));
  $("#events").prepend(item);
}

const COURSE = [
  ["search", "Recherche"],
  ["registration", "Inscription"],
  ["accommodation", "Hébergement"],
  ["transport", "Transport"],
  ["finish", "À vous de signer"],
];
const STEP_STATE = {
  pending: "todo",
  running: "active",
  paused: "active",
  waiting_for_user: "waiting",
  stopped_before_commitment: "done",
  completed: "done",
  failed: "failed",
};
const STEP_NOTE = {
  running: "en cours",
  paused: "en pause",
  waiting_for_user: "question pour vous",
  stopped_before_commitment: "prêt à signer",
  completed: "terminé",
  failed: "échec",
};

function renderCourse(data) {
  const course = $("#course");
  course.replaceChildren();
  const byKind = Object.fromEntries(data.steps.map((step) => [step.kind, step]));
  const settled = data.steps.length > 0 && data.steps.every((step) => STEP_STATE[step.status] === "done" || step.status === "failed");
  COURSE.forEach(([kind, label], index) => {
    let state = "todo";
    let note = "";
    if (kind === "search") {
      state = data.race ? "done" : data.status === "failed" ? "failed" : "active";
      note = data.race ? "course trouvée" : "Linkup cherche";
    } else if (kind === "finish") {
      state = settled ? "active" : "todo";
      note = settled ? "à vous" : "";
    } else if (byKind[kind]) {
      state = STEP_STATE[byKind[kind].status] || "todo";
      note = STEP_NOTE[byKind[kind].status] || "";
    }
    const item = element("li");
    item.dataset.state = state;
    item.append(element("span", state === "done" ? "✓" : String(index + 1), "cp"), element("span", label), element("span", note, "cp-note"));
    course.append(item);
  });
}

function renderDistance(race) {
  const node = $("#race-distance");
  node.replaceChildren();
  if (!race || !race.distance_km) {
    node.textContent = "…";
    return;
  }
  node.append(String(race.distance_km).replace(".", ","), element("small", "km"));
}

function render(data, withEvents = false) {
  mission = data;
  $("#mission").classList.remove("hidden");
  $("#mission-id").textContent = data.id;
  $("#mission-status").textContent = MISSION_LABELS[data.status] || data.status;
  renderRace(data.race);
  data.steps.forEach(renderStep);
  renderPortal(data.steps);
  renderCourse(data);
  renderDistance(data.race);
  renderActivity(data);
  const anyRunning = data.steps.some((step) => step.status === "running");
  const anyPaused = data.steps.some((step) => step.status === "paused");
  $("#pause-all").disabled = !anyRunning;
  $("#resume-all").disabled = !anyPaused;
  if (withEvents) {
    $("#events").replaceChildren();
    data.events.forEach(appendEvent);
  }
}

function listen(id) {
  if (source) source.close();
  source = new EventSource(`/api/missions/${id}/events`);
  source.addEventListener("snapshot", (event) => render(JSON.parse(event.data), true));
  source.addEventListener("mission", (event) => {
    const data = JSON.parse(event.data);
    render(data);
    if (TERMINAL.has(data.status)) source.close();
  });
  source.addEventListener("trace", (event) => appendEvent(JSON.parse(event.data)));
  source.addEventListener("question", () => {
    if (mission) api(`/api/missions/${mission.id}`).then((data) => render(data));
  });
  source.addEventListener("end", () => source.close());
}

async function control(kind, action, body) {
  try {
    await api(`/api/missions/${mission.id}/steps/${kind}/${action}`, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (error) {
    alert(error.message);
  }
}

$("#pause-all").addEventListener("click", () => api(`/api/missions/${mission.id}/pause`, { method: "POST" }));
$("#resume-all").addEventListener("click", () => api(`/api/missions/${mission.id}/resume`, { method: "POST" }));

$("#mission-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = $("#query").value.trim();
  if (!query) return;
  $("#steps").replaceChildren();
  const data = await api("/api/missions", { method: "POST", body: JSON.stringify({ query }) });
  history.replaceState(null, "", `?mission=${data.id}`);
  render(data, true);
  listen(data.id);
});

let recorder = null;
async function transcribe(blob, input, feedback, note) {
  feedback.textContent = "Transcription…";
  const data = await api("/api/transcribe", {
    method: "POST",
    headers: { "Content-Type": blob.type || "application/octet-stream" },
    body: blob,
  });
  input.value = data.text;
  feedback.textContent = note || "Transcription reçue.";
}

async function captureToInput(input, button, feedback) {
  if (recorder && recorder.state === "recording") {
    recorder.stop();
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const chunks = [];
    recorder = new MediaRecorder(stream);
    recorder.target = input;
    recorder.button = button;
    recorder.ondataavailable = (event) => chunks.push(event.data);
    recorder.onstop = () => {
      const stoppedRecorder = recorder;
      stoppedRecorder.transcribing = true;
      stream.getTracks().forEach((track) => track.stop());
      button.textContent = button.id === "mic" ? "Dire la course" : "Micro";
      transcribe(new Blob(chunks, { type: recorder.mimeType }), input, feedback)
        .catch((error) => (feedback.textContent = `Transcription impossible : ${error.message}`))
        .finally(() => {
          if (recorder === stoppedRecorder) recorder = null;
        });
    };
    recorder.start();
    button.textContent = "Arrêter";
    feedback.textContent = "Enregistrement… cliquez sur « Arrêter » quand vous avez fini.";
  } catch (error) {
    if (!simulated) {
      feedback.textContent = `Micro indisponible : ${error.message}`;
      return;
    }
    transcribe(
      new Blob(["demo"], { type: "text/plain" }),
      input,
      feedback,
      "Micro indisponible : transcription simulée.",
    ).catch((transcribeError) => (feedback.textContent = `Transcription impossible : ${transcribeError.message}`));
  }
}

async function submitAnswer(questionId, answer, item) {
  const feedback = $(".question-feedback", item);
  if (!answer) {
    if (feedback) feedback.textContent = "Saisissez ou choisissez une réponse.";
    return;
  }
  try {
    const data = await api(
      `/api/missions/${mission.id}/questions/${questionId}/answer`,
      { method: "POST", body: JSON.stringify({ answer }) },
    );
    render(data);
  } catch (error) {
    if (feedback) feedback.textContent = error.message;
  }
}

$("#mic").addEventListener("click", () => captureToInput($("#query"), $("#mic"), $("#mic-status")));

(async () => {
  const health = await api("/api/health");
  simulated = health.simulated;
  $("#mode").textContent = simulated ? "Mode démo : agents simulés" : "Mode réel";
  $("#mode").classList.toggle("real", !simulated);
  $("#mode").classList.remove("hidden");
  const existing = new URLSearchParams(location.search).get("mission");
  if (existing) {
    try {
      render(await api(`/api/missions/${existing}`), true);
      listen(existing);
    } catch {
      history.replaceState(null, "", "/");
    }
  }
})();
