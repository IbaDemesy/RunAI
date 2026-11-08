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
    verified: "Verified: sourced geometry, not a booking.",
    approximate: "Approximate: estimated geometry, please verify.",
    illustrative: "Illustrative: indicative link, not a route to follow.",
    unavailable: "Route unavailable: no invented itinerary.",
  };
  const MODES = { live: "Live", demo: "Demo: fictional data", replay: "Replay: recorded, not live" };
  const TRANSPORT = { walk: "Walk", local: "Local transport", train: "Train", flight: "Flight", race: "Race" };
  const AUTOMATION = { automated: "Automated preparation, nothing booked", manual: "Finish manually", not_covered: "Not automated" };
  const STATUS = { available: "Available", partial: "Partial", unavailable: "To complete" };
  const CONFIDENCE = { verified: "verified", estimated: "estimated", illustrative: "illustrative", unknown: "unverified" };

  function safeUrl(value) {
    try {
      const url = new URL(value);
      return ["http:", "https:"].includes(url.protocol) ? url.href : null;
    } catch (_) {
      return null;
    }
  }

  function moneyText(money) {
    if (!money) return "Price unknown";
    try {
      return new Intl.NumberFormat("en-GB", { style: "currency", currency: money.currency, minimumFractionDigits: Number.isInteger(money.amount) ? 0 : 2, maximumFractionDigits: 2 }).format(money.amount);
    } catch (_) {
      return `${money.amount} ${money.currency}`;
    }
  }

  // errorTarget can be the map/timeline common ancestor. E3 owns hiding/destroying the failed map.
  function createJourneyView(container, options = {}) {
    if (!contract) throw new Error("Load journey-contract.js before the journey fallback.");
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
    root.setAttribute("aria-label", "Trip without a map");
    root.hidden = !!options.hiddenUntilError;
    const live = el("p", "Choose a trip to show its timeline.", "journey-status");
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
        node.setAttribute("aria-label", `${label} (new tab)`);
      }
      parent.append(node);
    }

    function addLimitation(parent, limitation) {
      if (!limitation) return;
      const p = el("p", limitation.message, "journey-limitation");
      if (safeUrl(limitation.manual_url)) {
        p.append(el("span", " "));
        addLink(p, "Check the official site manually", limitation.manual_url);
      }
      parent.append(p);
    }

    function timeText(value, timezone) {
      return value ? `${value.replace("T", " ")} (${timezone || plan.timezone})` : "Time not provided";
    }

    function renderBudget() {
      const budget = plan.budget;
      const section = el("section", undefined, "journey-budget");
      section.setAttribute("aria-label", "Trip budget");
      section.append(el("h3", "Budget"));
      section.append(el("p", `${budget.complete ? "Known total" : "Partial total"} : ${moneyText({ amount: budget.known_total, currency: budget.currency })}`));
      const list = el("ul");
      for (const line of budget.lines) {
        const li = el("li", `${line.label} : ${moneyText(line.money)}${line.note ? ` — ${line.note}` : ""}`);
        if (line.money) li.append(el("span", ` (${CONFIDENCE[line.money.confidence] || "unverified"}, collected: ${line.money.collected_at})`));
        list.append(li);
      }
      section.append(list);
      if (!budget.complete) section.append(el("p", "Missing prices are not counted as zero. The final total is unknown."));
      if (budget.cap != null) {
        section.append(el("p", `Cap: ${moneyText({ amount: budget.cap, currency: budget.currency })}. ${budget.over_cap === true ? "Over cap." : budget.over_cap === false ? "Known total within cap." : "Cap not assessable with missing prices."}`));
      }
      return section;
    }

    function renderSources() {
      const section = el("section", undefined, "journey-sources");
      section.setAttribute("aria-label", "Sources and credits");
      section.append(el("h3", "Sources and credits"));
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
        li.append(el("span", ` — ${source.kind || "unknown origin"}, collected: ${source.collected_at || "date unknown"}`));
        list.append(li);
      }
      for (const credit of options.attributions || []) {
        const li = el("li");
        addLink(li, credit.label, credit.url);
        list.append(li);
      }
      if (!list.children.length) list.append(el("li", "No source provided: please verify this information."));
      section.append(list, el("p", "Map-free view: no tiles loaded. Map credits remain visible in the map view when used."));
      return section;
    }

    function render() {
      buttons = new Map();
      articles = new Map();
      actions = new Map();
      playButton = null;
      pauseButton = null;
      content.replaceChildren();
      if (!plan) return;
      const header = el("header");
      header.append(el("h2", "Your trip, step by step"), el("p", MODES[plan.mode], "journey-mode"));
      header.append(el("p", `From ${plan.origin_public} — ${plan.date_range ? plan.date_range.join(" to ") : "Dates to confirm"} — trip timezone: ${plan.timezone}`));
      header.append(el("p", "Prepared does not mean booked. No binding actions from this view."));
      const legend = el("ul", undefined, "journey-legend");
      legend.setAttribute("aria-label", "Route legend");
      for (const [status, label] of Object.entries(GEOMETRY)) {
        const li = el("li", label);
        li.setAttribute("data-geometry", status);
        legend.append(li);
      }
      const nav = el("nav");
      nav.setAttribute("aria-label", "Trip chapters");
      const controls = el("div", undefined, "journey-controls");
      for (const [action, label] of [["previous", "Previous chapter"], ["play", "Play timeline"], ["pause", "Pause"], ["next", "Next chapter"]]) {
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
        article.append(el("h3", chapter.label), el("p", STATUS[chapter.status] || "To complete", "journey-chapter-state"));
        for (const stopId of chapter.stop_ids) {
          const stop = stops.get(stopId);
          article.append(el("p", stop.label, "journey-stop"));
          article.append(el("p", `${timeText(stop.local_time, stop.timezone)}${stop.coords ? "" : " — Location not provided"}`));
        }
        for (const segmentId of chapter.segment_ids) {
          const segment = segments.get(segmentId);
          const detail = el("div", undefined, "journey-segment");
          detail.setAttribute("data-geometry", segment.geometry_status);
          detail.append(el("p", `${TRANSPORT[segment.mode]} : ${stops.get(segment.from_stop_id).label} → ${stops.get(segment.to_stop_id).label}`));
          detail.append(el("p", GEOMETRY[segment.geometry_status]));
          detail.append(el("p", `Departure: ${timeText(segment.departure, segment.timezone)}; arrival: ${timeText(segment.arrival, segment.timezone)}`));
          detail.append(el("p", `${segment.duration_min == null ? "Duration unknown" : `${segment.duration_min} min`} — ${moneyText(segment.cost)}`));
          detail.append(el("p", AUTOMATION[segment.automation] || "Not automated"));
          if (safeUrl(segment.manual_url)) addLink(detail, "Open the official site manually", segment.manual_url);
          addLimitation(detail, segment.limitation);
          article.append(detail);
        }
        if (!chapter.stop_ids.length && !chapter.segment_ids.length) article.append(el("p", "Information not provided. Complete it with your input."));
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
      }
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
        live.textContent = "Timeline playback paused.";
        emit("playback", { state: "paused" });
      }
    }

    function showChapter(id) {
      if (destroyed || !plan) return false;
      const chapter = plan.chapters.find((item) => item.id === id);
      if (!chapter) throw new RangeError(`Unknown chapter: ${id}`);
      selected = id;
      updateSelection();
      live.textContent = `Chapter: ${chapter.label}. ${STATUS[chapter.status] || "To complete"}.`;
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
        live.textContent = "Reduced motion: use chapters without automatic playback.";
        return;
      }
      playing = true;
      updateControls();
      live.textContent = "Timeline playing. Pause stops only this view, not the agents.";
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
        live.textContent = "Trip unavailable: invalid data. Reload the trip.";
        emit("error", { error: "invalid-plan" });
        throw new TypeError(`Invalid JourneyPlan: ${errors.join(", ")}`);
      }
      plan = next;
      if (!recovery.hidden) recovery.textContent = "Map unavailable: your trip remains readable without it. Use chapters and manual links.";
      selected = next.chapters.some((c) => c.id === selected) ? selected : (next.chapters[0] || {}).id || null;
      render();
      if (focusChapter && buttons.has(focusChapter)) buttons.get(focusChapter).focus();
      if (focusAction) {
        const replacement = actions.get(focusAction);
        if (replacement && !replacement.disabled) replacement.focus();
        else if (playButton && !playButton.disabled) playButton.focus();
        else if (buttons.size) buttons.values().next().value.focus();
      }
      live.textContent = reduced() ? "Reduced motion: navigate chapters manually." : "Trip available without a map. Choose a chapter.";
      emit("ready", { state: "fallback" });
    }

    function seekKm(km) {
      if (!Number.isFinite(km) || km < 0) throw new RangeError("Invalid distance");
      if (destroyed || !plan) return false;
      pause();
      if (plan.chapters.some((chapter) => chapter.id === "race")) showChapter("race");
      const segment = plan.segments.find((item) => item.mode === "race" && item.geometry && item.geometry.length >= 2);
      if (!segment || !route) {
        live.textContent = "Distance unavailable: no usable race route in this view.";
        return false;
      }
      const track = route.buildTrack(segment.geometry.map(([lon, lat]) => ({ lon, lat, ele: null })));
      const value = Math.min(km, track.totalM / 1000);
      live.textContent = `Race: km ${value.toLocaleString("en-GB", { maximumFractionDigits: 2 })}. ${GEOMETRY[segment.geometry_status]}`;
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
      live.textContent = plan ? "Map unavailable: your trip remains readable without it. Use chapters and manual links." : "Trip unavailable: reload its data.";
      recovery.textContent = live.textContent;
      recovery.hidden = false;
    }

    function onMotionChange() {
      if (reduced()) {
        pause();
        live.textContent = "Reduced motion: navigate chapters manually.";
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
      actions.clear();
      playButton = null;
      pauseButton = null;
      plan = null;
    }

    return { setPlan, showChapter, play, pause, seekKm, destroy };
  }

  return { createJourneyView, createJourneyFallback: createJourneyView };
});
