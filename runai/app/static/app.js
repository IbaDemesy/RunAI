const STATUS_LABELS = {
  pending: "En attente",
  running: "En cours",
  paused: "En pause",
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
    facts.append(element("dt", label), element("dd", value));
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

function renderStep(step) {
  const card = stepCard(step);
  card.dataset.status = step.status;
  $(".step-label", card).textContent = step.label;
  const status = $(".status", card);
  status.textContent = STATUS_LABELS[step.status] || step.status;
  status.className = `status status-${step.status}`;
  $(".last-action", card).textContent = step.data.last_action || (step.status === "pending" ? "Agent pas encore lancé" : "");
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
  const started = Boolean(step.h_session_id);
  const active = started && (step.status === "running" || step.status === "paused");
  $(".pause", card).disabled = !started || step.status !== "running";
  $(".resume", card).disabled = !started || step.status !== "paused";
  $(".message", card).classList.toggle("hidden", !active);
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
  const waiting = steps.filter((step) => ["pending", "running", "paused"].includes(step.status)).length;
  $("#portal-total").textContent =
    `Total estimé à payer vous-même : ${total.toFixed(2)} €` + (waiting ? ` · ${waiting} agent(s) encore en cours` : "");
}

function appendEvent(event) {
  const item = element("li");
  const time = new Date(event.at).toLocaleTimeString("fr-FR");
  item.append(element("time", time), element("span", event.source, `source source-${event.source.split(":")[0]}`), element("span", event.message || event.type));
  $("#events").prepend(item);
}

function render(data, withEvents = false) {
  mission = data;
  $("#mission").classList.remove("hidden");
  $("#mission-id").textContent = data.id;
  $("#mission-status").textContent = MISSION_LABELS[data.status] || data.status;
  renderRace(data.race);
  data.steps.forEach(renderStep);
  renderPortal(data.steps);
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
async function transcribe(blob, note) {
  $("#mic-status").textContent = "Transcription…";
  const response = await fetch("/api/transcribe", {
    method: "POST",
    headers: { "Content-Type": blob.type || "application/octet-stream" },
    body: blob,
  });
  const data = await response.json();
  $("#query").value = data.text;
  $("#mic-status").textContent = note || "Transcription reçue : vérifiez puis cliquez sur « Préparer ».";
}

$("#mic").addEventListener("click", async () => {
  if (recorder && recorder.state === "recording") {
    recorder.stop();
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const chunks = [];
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (event) => chunks.push(event.data);
    recorder.onstop = () => {
      stream.getTracks().forEach((track) => track.stop());
      $("#mic").textContent = "Dire la course";
      transcribe(new Blob(chunks, { type: recorder.mimeType }));
    };
    recorder.start();
    $("#mic").textContent = "Arrêter";
    $("#mic-status").textContent = "Enregistrement… cliquez sur « Arrêter » quand vous avez fini.";
  } catch (error) {
    if (!simulated) {
      $("#mic-status").textContent = `Micro indisponible : ${error.message}`;
      return;
    }
    transcribe(new Blob(["demo"], { type: "text/plain" }), "Micro indisponible : transcription simulée.");
  }
});

(async () => {
  const health = await api("/api/health");
  simulated = health.simulated;
  $("#mode").classList.toggle("hidden", !simulated);
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
