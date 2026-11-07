/* JourneyPlan map player (createJourneyView, see journey-contract.js); load journey-contract.js, route.js, journey-data.js first. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./journey-contract.js"), require("./journey-data.js"), root);
  } else {
    root.RunAIJourneyPlayer = factory(root.RunAIJourneyContract, root.RunAIJourneyData, root);
  }
})(typeof self !== "undefined" ? self : this, function (contract, journeyData, root) {
  "use strict";

  const SOURCES = { stops: "runai-journey-stops", segments: "runai-journey-segments" };
  const MODE_COLOR = ["match", ["get", "mode"],
    "walk", "#16a34a", "local", "#f97316", "train", "#7c3aed", "flight", "#2563eb", "race", "#dc2626", "#64748b"];
  const LAYERS = [
    { id: "runai-journey-segments-line", source: SOURCES.segments, type: "line",
      filter: ["==", ["get", "geometry_status"], "verified"],
      paint: { "line-width": 3, "line-color": MODE_COLOR } },
    { id: "runai-journey-segments-dashed", source: SOURCES.segments, type: "line",
      filter: ["all", ["!=", ["get", "geometry_status"], "verified"], ["!=", ["get", "geometry_status"], "unavailable"]],
      paint: { "line-width": 3, "line-color": MODE_COLOR, "line-dasharray": [2, 2] } },
    { id: "runai-journey-stops-circle", source: SOURCES.stops, type: "circle",
      paint: { "circle-radius": 6, "circle-color": "#f97316", "circle-stroke-color": "#fff", "circle-stroke-width": 2 } },
  ];

  /*
   * Camera-only player: every method moves the map or the RunAIFlyover race
   * view and emits MAP_EVENTS; nothing here reaches missions or H agents.
   * Options: map (MapLibre-like, default RunAIFlyover.map), flyover (default
   * RunAIFlyover), reducedMotion, dwellMs, pollMs, setTimeout/clearTimeout.
   */
  function createJourneyView(container, options) {
    const opts = options || {};
    const globalFlyover = root && root.RunAIFlyover;
    const map = opts.map || (globalFlyover && globalFlyover.map) || null;
    const flyover = opts.flyover !== undefined ? opts.flyover : globalFlyover || null;
    const reducedMotion = Boolean(opts.reducedMotion);
    const dwellMs = Number.isFinite(opts.dwellMs) ? opts.dwellMs : 4000;
    const pollMs = Number.isFinite(opts.pollMs) ? opts.pollMs : 500;
    const schedule = opts.setTimeout || ((fn, ms) => setTimeout(fn, ms));
    const cancel = opts.clearTimeout || ((id) => clearTimeout(id));
    const EventCtor = opts.CustomEvent || (typeof CustomEvent === "function" ? CustomEvent : null);

    const state = { plan: null, data: null, chapterId: null, playback: "idle", timer: null, generation: 0, destroyed: false };

    function emit(name, extra) {
      const detail = Object.assign({ planRevision: state.plan ? state.plan.revision : null }, extra);
      if (container && typeof container.dispatchEvent === "function" && EventCtor) {
        container.dispatchEvent(new EventCtor(name, { detail }));
      }
      return detail;
    }

    function fail(code, message, extra) {
      emit(contract.MAP_EVENTS.error, Object.assign({ error: { code, message }, fatal: code === "invalid_plan" }, extra));
      return false;
    }

    function setPlayback(next, chapterId) {
      state.playback = next;
      emit(contract.MAP_EVENTS.playback, { state: next, chapterId: chapterId === undefined ? state.chapterId : chapterId });
    }

    function clearTimer() {
      if (state.timer !== null) cancel(state.timer);
      state.timer = null;
    }

    function duration(ms) {
      return reducedMotion ? 0 : ms;
    }

    function renderLayers(data) {
      if (!map || typeof map.addSource !== "function") return;
      for (const [key, id] of Object.entries(SOURCES)) {
        const source = typeof map.getSource === "function" ? map.getSource(id) : null;
        if (source && typeof source.setData === "function") source.setData(data[key]);
        else map.addSource(id, { type: "geojson", data: data[key] });
      }
      for (const layer of LAYERS) {
        if (typeof map.getLayer === "function" && map.getLayer(layer.id)) continue;
        if (typeof map.addLayer === "function") map.addLayer(layer);
      }
    }

    function removeLayers() {
      if (!map) return;
      for (const layer of LAYERS) {
        if (typeof map.getLayer === "function" && map.getLayer(layer.id) && typeof map.removeLayer === "function") map.removeLayer(layer.id);
      }
      for (const id of Object.values(SOURCES)) {
        if (typeof map.getSource === "function" && map.getSource(id) && typeof map.removeSource === "function") map.removeSource(id);
      }
    }

    function frame(bounds, ms) {
      if (!map || !bounds) return;
      const [min, max] = bounds;
      if (min[0] === max[0] && min[1] === max[1]) {
        const camera = { center: min.slice(), zoom: 14 };
        if (reducedMotion || typeof map.easeTo !== "function") map.jumpTo(camera);
        else map.easeTo(Object.assign(camera, { duration: ms }));
      } else if (typeof map.fitBounds === "function") {
        map.fitBounds([min.slice(), max.slice()], { padding: 60, duration: duration(ms) });
      }
    }

    function stopCamera() {
      if (map && typeof map.stop === "function") map.stop();
      if (state.chapterId === "race" && flyover && typeof flyover.pause === "function") flyover.pause();
    }

    function chapterOf(chapterId) {
      return (state.plan.chapters || []).find((chapter) => chapter.id === chapterId) || null;
    }

    function chapterAvailability(chapterId) {
      const chapter = chapterOf(chapterId);
      if (!chapter) return { available: false, reason: "chapter_missing" };
      if (chapter.status === "unavailable") return { available: false, reason: "chapter_unavailable" };
      if (!state.data.chapterBounds[chapterId]) return { available: false, reason: "chapter_unplaced" };
      return { available: true, status: chapter.status || "available" };
    }

    function moveToChapter(chapterId) {
      const availability = chapterAvailability(chapterId);
      state.chapterId = chapterId;
      if (!availability.available) {
        emit(contract.MAP_EVENTS.chapter, { chapterId, state: "unavailable", reason: availability.reason });
        fail(availability.reason, `Chapitre ${chapterId} non affichable : aucune position sourcée.`, { chapterId });
        return false;
      }
      frame(state.data.chapterBounds[chapterId], 1200);
      emit(contract.MAP_EVENTS.chapter, { chapterId, state: availability.status });
      return true;
    }

    function guard() {
      if (state.destroyed) return fail("destroyed", "Vue détruite.");
      if (!state.plan) return fail("no_plan", "Aucun JourneyPlan chargé.");
      return true;
    }

    function setPlan(plan) {
      if (state.destroyed) return fail("destroyed", "Vue détruite.");
      let data;
      try {
        data = journeyData.buildJourneyData(plan);
      } catch (error) {
        return fail("invalid_plan", error.message, { errors: error.errors || [] });
      }
      const wasPlaying = state.playback === "playing";
      state.generation += 1;
      clearTimer();
      if (wasPlaying) stopCamera();
      state.plan = plan;
      state.data = data;
      state.chapterId = null;
      renderLayers(data);
      frame(data.bounds, 800);
      if (wasPlaying) setPlayback("stopped", null);
      else state.playback = "idle";
      emit(contract.MAP_EVENTS.ready, { state: data.bounds ? "overview" : "unplaced", unplaced: data.unplaced.length, unmapped: data.unmapped.length });
      return true;
    }

    function showChapter(chapterId) {
      if (!guard()) return false;
      if (!contract.CHAPTER_IDS.includes(chapterId)) return fail("unknown_chapter", `Chapitre inconnu : ${chapterId}`, { chapterId });
      if (state.playback === "playing") pause();
      return moveToChapter(chapterId);
    }

    function raceTrackLoaded() {
      return Boolean(flyover && flyover.state && flyover.state.totalM > 0);
    }

    function step(index, generation) {
      if (generation !== state.generation || state.playback !== "playing") return;
      const ids = (state.plan.chapters || []).map((chapter) => chapter.id);
      if (index >= ids.length) {
        state.timer = null;
        setPlayback("ended");
        return;
      }
      const chapterId = ids[index];
      const shown = moveToChapter(chapterId);
      if (generation !== state.generation || state.playback !== "playing") return;
      if (shown && chapterId === "race" && raceTrackLoaded() && typeof flyover.play === "function") {
        flyover.play();
        const wait = () => {
          if (generation !== state.generation || state.playback !== "playing") return;
          state.timer = flyover.state.playing ? schedule(wait, pollMs) : schedule(() => step(index + 1, generation), 0);
        };
        state.timer = schedule(wait, pollMs);
        return;
      }
      state.timer = schedule(() => step(index + 1, generation), shown ? dwellMs : 0);
    }

    function play() {
      if (!guard()) return false;
      if (state.playback === "playing") return true;
      const ids = (state.plan.chapters || []).map((chapter) => chapter.id);
      if (!ids.length) return fail("no_chapters", "Aucun chapitre dans le JourneyPlan.");
      let start = 0;
      if (state.playback === "paused" && state.chapterId !== null) start = Math.max(0, ids.indexOf(state.chapterId));
      state.generation += 1;
      setPlayback("playing", ids[start]);
      step(start, state.generation);
      return true;
    }

    function pause() {
      if (state.destroyed || state.playback !== "playing") return false;
      state.generation += 1;
      clearTimer();
      stopCamera();
      setPlayback("paused");
      return true;
    }

    function seekKm(km) {
      if (!guard()) return false;
      if (!Number.isFinite(km) || km < 0) return fail("invalid_km", `Kilomètre invalide : ${km}`, { chapterId: "race" });
      const race = (state.plan.segments || []).find((segment) => segment.mode === "race");
      if (!race || race.geometry_status === "unavailable" || !raceTrackLoaded() || typeof flyover.seekKm !== "function") {
        return fail("race_track_unavailable", "Tracé de course non disponible : pas de positionnement au km.", { chapterId: "race" });
      }
      if (state.playback === "playing") pause();
      if (state.chapterId !== "race") {
        state.chapterId = "race";
        emit(contract.MAP_EVENTS.chapter, { chapterId: "race", state: (chapterOf("race") || {}).status || "available" });
      }
      flyover.seekKm(km);
      return true;
    }

    function destroy() {
      if (state.destroyed) return;
      state.generation += 1;
      clearTimer();
      if (state.playback === "playing") stopCamera();
      removeLayers();
      state.destroyed = true;
      state.playback = "destroyed";
    }

    return {
      setPlan, showChapter, play, pause, seekKm, destroy,
      get state() {
        return { planRevision: state.plan ? state.plan.revision : null, chapterId: state.chapterId, playback: state.playback };
      },
    };
  }

  return { createJourneyView, SOURCES, LAYERS };
});
