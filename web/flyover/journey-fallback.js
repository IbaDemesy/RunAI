/* Accessible, network-free JourneyPlan timeline. Load journey-contract.js first; route.js enables km seeking. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./journey-contract.js"), require("./route.js"));
  } else {
    root.RunAIJourneyFallback = factory(root.RunAIJourneyContract, root.RunAIRoute);
  }
})(typeof self !== "undefined" ? self : this, function (contract, route) {
  "use strict";

  const GEOMETRY = {
    verified: "Vérifié : géométrie sourcée, pas une réservation.",
    approximate: "Approximatif : géométrie estimée, à vérifier.",
    illustrative: "Illustratif : liaison indicative, pas un itinéraire à suivre.",
    unavailable: "Tracé indisponible : aucun itinéraire inventé.",
  };
  const MODES = { live: "Réel (live)", demo: "Démonstration : données fictives", replay: "Replay : enregistrement, pas du direct" };
  const TRANSPORT = { walk: "Marche", local: "Transport local", train: "Train", flight: "Vol", race: "Course" };
  const AUTOMATION = { automated: "Préparation automatisée, rien de réservé", manual: "À finaliser manuellement", not_covered: "Non automatisé" };
  const STATUS = { available: "Renseigné", partial: "Partiel", unavailable: "À compléter" };
  const CONFIDENCE = { verified: "vérifié", estimated: "estimé", illustrative: "illustratif", unknown: "non vérifié" };

  function safeUrl(value) {
    try {
      const url = new URL(value);
      return ["http:", "https:"].includes(url.protocol) ? url.href : null;
    } catch (_) {
      return null;
    }
  }

  function moneyText(money) {
    if (!money) return "Prix inconnu";
    try {
      return new Intl.NumberFormat("fr-FR", { style: "currency", currency: money.currency }).format(money.amount);
    } catch (_) {
      return `${money.amount} ${money.currency}`;
    }
  }

  // errorTarget can be the map/timeline common ancestor. E3 owns hiding/destroying the failed map.
  function createJourneyView(container, options = {}) {
    if (!contract) throw new Error("Charger journey-contract.js avant le repli du séjour.");
    const doc = container.ownerDocument;
    const win = doc.defaultView;
    const errorTarget = options.errorTarget || container;
    const media = win.matchMedia ? win.matchMedia("(prefers-reduced-motion: reduce)") : null;
    const reduced = () => options.reducedMotion === true || !!(media && media.matches);
    let plan = null;
    let selected = null;
    let timer = null;
    let playing = false;
    let destroyed = false;
    let buttons = new Map();
    let articles = new Map();
    let disclosures = new Map();
    let narrow = false;
    let actions = new Map();
    let playButton;
    let pauseButton;

    function el(tag, text, className) {
      const node = doc.createElement(tag);
      if (text !== undefined) node.textContent = text;
      if (className) node.setAttribute("class", className);
      return node;
    }

    const root = el("section", undefined, "journey-fallback");
    root.setAttribute("aria-label", "Séjour sans carte");
    root.hidden = !!options.hiddenUntilError;
    const live = el("p", "Choisissez un séjour pour afficher sa timeline.", "journey-status");
    live.setAttribute("role", "status");
    live.setAttribute("aria-live", "polite");
    live.setAttribute("aria-atomic", "true");
    const recovery = el("p", "", "journey-warning");
    recovery.hidden = true;
    const content = el("div", undefined, "journey-content");
    root.append(live, recovery, content);
    container.append(root);

    function emit(name, detail = {}) {
      if (destroyed) return;
      container.dispatchEvent(new win.CustomEvent(contract.MAP_EVENTS[name], {
        bubbles: true,
        detail: { planRevision: plan ? plan.revision : null, chapterId: selected, ...detail },
      }));
    }

    function addLink(parent, label, url) {
      const href = safeUrl(url);
      const node = el(href ? "a" : "span", label);
      if (href) {
        node.setAttribute("href", href);
        node.setAttribute("target", "_blank");
        node.setAttribute("rel", "noopener noreferrer");
        node.setAttribute("aria-label", `${label} (nouvel onglet)`);
      }
      parent.append(node);
    }

    function addLimitation(parent, limitation) {
      if (!limitation) return;
      const p = el("p", limitation.message, "journey-limitation");
      if (safeUrl(limitation.manual_url)) {
        p.append(el("span", " "));
        addLink(p, "Consulter le site manuellement", limitation.manual_url);
      }
      parent.append(p);
    }

    function timeText(value, timezone) {
      return value ? `${value.replace("T", " ")} (${timezone || plan.timezone})` : "Horaire non renseigné";
    }

    function renderBudget() {
      const budget = plan.budget;
      const section = el("section", undefined, "journey-budget");
      section.setAttribute("aria-label", "Budget du séjour");
      section.append(el("h3", "Budget"));
      section.append(el("p", `${budget.complete ? "Total renseigné" : "Total partiel"} : ${moneyText({ amount: budget.known_total, currency: budget.currency })}`));
      const list = el("ul");
      for (const line of budget.lines) {
        const li = el("li", `${line.label} : ${moneyText(line.money)}${line.note ? ` — ${line.note}` : ""}`);
        if (line.money) li.append(el("span", ` (${CONFIDENCE[line.money.confidence] || "non vérifié"}, collecte : ${line.money.collected_at})`));
        list.append(li);
      }
      section.append(list);
      if (!budget.complete) section.append(el("p", "Postes manquants non comptés comme zéro. Le total final reste inconnu."));
      if (budget.cap != null) {
        section.append(el("p", `Plafond : ${moneyText({ amount: budget.cap, currency: budget.currency })}. ${budget.over_cap === true ? "Plafond dépassé." : budget.over_cap === false ? "Total renseigné sous le plafond." : "Plafond non vérifiable avec les prix manquants."}`));
      }
      return section;
    }

    function renderSources() {
      const section = el("section", undefined, "journey-sources");
      section.setAttribute("aria-label", "Sources et attributions");
      section.append(el("h3", "Sources et attributions"));
      const list = el("ul");
      const seen = new Set();
      const provenances = [...(plan.sources || [])];
      for (const item of [...plan.stops, ...plan.segments, ...plan.budget.lines.map((line) => line.money).filter(Boolean)]) {
        if (item.provenance) provenances.push(item.provenance);
        if (item.cost && item.cost.provenance) provenances.push(item.cost.provenance);
      }
      for (const source of provenances) {
        const key = JSON.stringify(source);
        if (seen.has(key)) continue;
        seen.add(key);
        const li = el("li");
        addLink(li, source.label || source.kind || "Source", source.url);
        li.append(el("span", ` — ${source.kind || "origine inconnue"}, collecte : ${source.collected_at || "date inconnue"}`));
        list.append(li);
      }
      for (const credit of options.attributions || []) {
        const li = el("li");
        addLink(li, credit.label, credit.url);
        list.append(li);
      }
      if (!list.children.length) list.append(el("li", "Aucune source fournie : informations à vérifier."));
      section.append(list, el("p", "Vue sans fond de carte : aucune tuile chargée. Les crédits de la carte, si utilisée, restent à afficher dans sa vue."));
      return section;
    }

    function render() {
      buttons = new Map();
      articles = new Map();
      disclosures = new Map();
      narrow = win.matchMedia?.('(max-width: 640px)')?.matches ?? false;
      actions = new Map();
      playButton = null;
      pauseButton = null;
      content.replaceChildren();
      if (!plan) return;
      const header = el("header");
      header.append(el("h2", "Mon séjour, étape par étape"), el("p", MODES[plan.mode], "journey-mode"));
      header.append(el("p", `Depuis ${plan.origin_public} — ${plan.date_range ? plan.date_range.join(" au ") : "Dates à préciser"} — fuseau du séjour : ${plan.timezone}`));
      header.append(el("p", "Préparé ne signifie pas réservé. Aucune action engageante depuis cette vue."));
      const legend = el("ul", undefined, "journey-legend");
      legend.setAttribute("aria-label", "Légende des tracés");
      for (const [status, label] of Object.entries(GEOMETRY)) {
        const li = el("li", label);
        li.setAttribute("data-geometry", status);
        legend.append(li);
      }
      const nav = el("nav");
      nav.setAttribute("aria-label", "Chapitres du séjour");
      const controls = el("div", undefined, "journey-controls");
      for (const [action, label] of [["previous", "Chapitre précédent"], ["play", "Lire la timeline"], ["pause", "Pause"], ["next", "Chapitre suivant"]]) {
        const button = el("button", label);
        button.setAttribute("type", "button");
        button.setAttribute("data-action", action);
        actions.set(action, button);
        if (action === "play") playButton = button;
        if (action === "pause") pauseButton = button;
        controls.append(button);
      }
      const chapters = el("ol", undefined, "journey-chapters");
      const timeline = el("ol", undefined, "journey-timeline");
      const stops = new Map(plan.stops.map((stop) => [stop.id, stop]));
      const segments = new Map(plan.segments.map((segment) => [segment.id, segment]));
      for (const chapter of plan.chapters) {
        const li = el("li");
        const button = el("button", chapter.label);
        button.setAttribute("type", "button");
        button.setAttribute("data-chapter", chapter.id);
        buttons.set(chapter.id, button);
        li.append(button);
        chapters.append(li);
        const item = el("li");
        const article = el("article");
        article.setAttribute("aria-label", chapter.label);
        const disclosure = el("details");
        const summary = el("summary", chapter.label);
        disclosure.append(summary);
        disclosure.open = !narrow || chapter.id === selected;
        disclosure.addEventListener("toggle", () => {
          if (chapter.id === selected) disclosure.open = true;
        });
        disclosures.set(chapter.id, disclosure);
        article.append(disclosure);
        disclosure.append(el("p", STATUS[chapter.status] || "À compléter", "journey-chapter-state"));
        for (const stopId of chapter.stop_ids) {
          const stop = stops.get(stopId);
          disclosure.append(el("p", stop.label, "journey-stop"));
          disclosure.append(el("p", `${timeText(stop.local_time, stop.timezone)}${stop.coords ? "" : " — Localisation non renseignée"}`));
        }
        for (const segmentId of chapter.segment_ids) {
          const segment = segments.get(segmentId);
          const detail = el("div", undefined, "journey-segment");
          detail.setAttribute("data-geometry", segment.geometry_status);
          detail.append(el("p", `${TRANSPORT[segment.mode]} : ${stops.get(segment.from_stop_id).label} → ${stops.get(segment.to_stop_id).label}`));
          detail.append(el("p", GEOMETRY[segment.geometry_status]));
          detail.append(el("p", `Départ : ${timeText(segment.departure, segment.timezone)} ; arrivée : ${timeText(segment.arrival, segment.timezone)}`));
          detail.append(el("p", `${segment.duration_min == null ? "Durée inconnue" : `${segment.duration_min} min`} — ${moneyText(segment.cost)}`));
          detail.append(el("p", AUTOMATION[segment.automation] || "Non automatisé"));
          if (safeUrl(segment.manual_url)) addLink(detail, "Ouvrir le site manuellement", segment.manual_url);
          addLimitation(detail, segment.limitation);
          disclosure.append(detail);
        }
        if (!chapter.stop_ids.length && !chapter.segment_ids.length) disclosure.append(el("p", "Informations non renseignées. À compléter avec vous."));
        articles.set(chapter.id, article);
        item.append(article);
        timeline.append(item);
      }
      nav.append(controls, chapters);
      content.append(header, legend, nav, timeline, renderBudget());
      for (const warning of plan.warnings || []) content.append(el("p", warning, "journey-warning"));
      for (const limitation of plan.limitations || []) addLimitation(content, limitation);
      content.append(renderSources());
      updateSelection();
      updateControls();
    }

    function updateSelection() {
      for (const [id, button] of buttons) {
        if (id === selected) button.setAttribute("aria-current", "step");
        else button.removeAttribute("aria-current");
        articles.get(id).setAttribute("data-selected", String(id === selected));
        disclosures.get(id).open = !narrow || id === selected;
      }
      buttons.get(selected)?.scrollIntoView?.({ inline: 'nearest', block: 'nearest' });
    }

    function updateControls() {
      if (!playButton) return;
      playButton.disabled = playing || reduced() || !plan || !plan.chapters.length;
      pauseButton.disabled = !playing;
    }

    function pause() {
      if (destroyed) return;
      if (timer !== null) win.clearTimeout(timer);
      timer = null;
      const wasPlaying = playing;
      playing = false;
      updateControls();
      if (wasPlaying) {
        live.textContent = "Lecture de la timeline en pause.";
        emit("playback", { state: "paused" });
      }
    }

    function showChapter(id) {
      if (destroyed || !plan) return false;
      const chapter = plan.chapters.find((item) => item.id === id);
      if (!chapter) throw new RangeError(`Chapitre inconnu : ${id}`);
      selected = id;
      updateSelection();
      live.textContent = `Chapitre : ${chapter.label}. ${STATUS[chapter.status] || "À compléter"}.`;
      emit("chapter");
      return true;
    }

    function schedule() {
      timer = win.setTimeout(() => {
        timer = null;
        if (!playing || destroyed) return;
        const index = plan.chapters.findIndex((chapter) => chapter.id === selected);
        if (index + 1 >= plan.chapters.length) { pause(); return; }
        showChapter(plan.chapters[index + 1].id);
        schedule();
      }, 5000);
    }

    function play() {
      if (destroyed || root.hidden || !plan || !plan.chapters.length || playing) return;
      if (reduced()) {
        live.textContent = "Mouvement réduit : utilisez les chapitres sans lecture automatique.";
        return;
      }
      playing = true;
      updateControls();
      live.textContent = "Lecture de la timeline. Pause arrête uniquement cette vue, pas les agents.";
      emit("playback", { state: "playing" });
      schedule();
    }

    function setPlan(next) {
      if (destroyed) return;
      pause();
      const active = root.contains(doc.activeElement) ? doc.activeElement : null;
      const focusChapter = active && active.getAttribute("data-chapter");
      const focusAction = active && active.getAttribute("data-action");
      let errors;
      try {
        if (!next || ![next.stops, next.segments, next.chapters, next.budget && next.budget.lines].every(Array.isArray)) throw new Error("structure");
        errors = contract.validateJourneyPlan(next);
      } catch (_) { errors = ["structure"]; }
      if (errors.length) {
        plan = null;
        selected = null;
        render();
        root.hidden = false;
        live.textContent = "Séjour indisponible : données invalides. Rechargez le séjour.";
        emit("error", { error: "invalid-plan" });
        throw new TypeError(`JourneyPlan invalide : ${errors.join(", ")}`);
      }
      plan = next;
      if (!recovery.hidden) recovery.textContent = "Carte indisponible : le séjour reste lisible sans carte. Utilisez les chapitres et les liens manuels.";
      selected = next.chapters.some((c) => c.id === selected) ? selected : (next.chapters[0] || {}).id || null;
      render();
      if (focusChapter && buttons.has(focusChapter)) buttons.get(focusChapter).focus();
      if (focusAction) {
        const replacement = actions.get(focusAction);
        if (replacement && !replacement.disabled) replacement.focus();
        else if (playButton && !playButton.disabled) playButton.focus();
        else if (buttons.size) buttons.values().next().value.focus();
      }
      live.textContent = reduced() ? "Mouvement réduit : navigation manuelle par chapitre." : "Séjour disponible sans carte. Choisissez un chapitre.";
      emit("ready", { state: "fallback" });
    }

    function seekKm(km) {
      if (!Number.isFinite(km) || km < 0) throw new RangeError("Distance invalide");
      if (destroyed || !plan) return false;
      pause();
      if (plan.chapters.some((chapter) => chapter.id === "race")) showChapter("race");
      const segment = plan.segments.find((item) => item.mode === "race" && item.geometry && item.geometry.length >= 2);
      if (!segment || !route) {
        live.textContent = "Distance non disponible : aucun tracé de course exploitable dans cette vue.";
        return false;
      }
      const track = route.buildTrack(segment.geometry.map(([lon, lat]) => ({ lon, lat, ele: null })));
      const value = Math.min(km, track.totalM / 1000);
      live.textContent = `Course : km ${value.toLocaleString("fr-FR", { maximumFractionDigits: 2 })}. ${GEOMETRY[segment.geometry_status]}`;
      emit("chapter", { km: value });
      return value;
    }

    function targetButton(event) {
      let node = event.target;
      while (node && node !== root) {
        if (node.tagName === "BUTTON") return node;
        node = node.parentNode;
      }
      return null;
    }

    function move(offset) {
      if (!plan || !plan.chapters.length) return;
      const index = plan.chapters.findIndex((chapter) => chapter.id === selected);
      showChapter(plan.chapters[(index + offset + plan.chapters.length) % plan.chapters.length].id);
    }

    function onClick(event) {
      const button = targetButton(event);
      if (!button || button.disabled) return;
      const chapter = button.getAttribute("data-chapter");
      if (chapter) { pause(); showChapter(chapter); return; }
      const action = button.getAttribute("data-action");
      if (action === "play") play();
      else if (action === "pause") pause();
      else { pause(); move(action === "previous" ? -1 : 1); }
    }

    function onKey(event) {
      const button = targetButton(event);
      if (!button || !button.getAttribute("data-chapter") || !["ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      pause();
      const index = plan.chapters.findIndex((chapter) => chapter.id === button.getAttribute("data-chapter"));
      const count = plan.chapters.length;
      const next = event.key === "Home" ? 0 : event.key === "End" ? count - 1 : (index + (["ArrowRight", "ArrowDown"].includes(event.key) ? 1 : -1) + count) % count;
      showChapter(plan.chapters[next].id);
      buttons.get(selected).focus();
    }

    function onError(event) {
      const detail = event.detail || {};
      if (detail.fatal === false) return;
      if (plan && detail.planRevision != null && detail.planRevision !== plan.revision) return;
      pause();
      root.hidden = false;
      live.textContent = plan ? "Carte indisponible : le séjour reste lisible sans carte. Utilisez les chapitres et les liens manuels." : "Séjour indisponible : rechargez ses données.";
      recovery.textContent = live.textContent;
      recovery.hidden = false;
    }

    function onMotionChange() {
      if (reduced()) {
        pause();
        live.textContent = "Mouvement réduit : navigation manuelle par chapitre.";
      }
      updateControls();
    }

    root.addEventListener("click", onClick);
    root.addEventListener("keydown", onKey);
    errorTarget.addEventListener(contract.MAP_EVENTS.error, onError);
    if (media && media.addEventListener) media.addEventListener("change", onMotionChange);

    function destroy() {
      if (destroyed) return;
      pause();
      destroyed = true;
      root.removeEventListener("click", onClick);
      root.removeEventListener("keydown", onKey);
      errorTarget.removeEventListener(contract.MAP_EVENTS.error, onError);
      if (media && media.removeEventListener) media.removeEventListener("change", onMotionChange);
      root.remove();
      content.replaceChildren();
      buttons.clear();
      articles.clear();
      disclosures.clear();
      actions.clear();
      playButton = null;
      pauseButton = null;
      plan = null;
    }

    return { setPlan, showChapter, play, pause, seekKm, destroy };
  }

  return { createJourneyView, createJourneyFallback: createJourneyView };
});
