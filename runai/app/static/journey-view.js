(function (root, factory) {
  const api = factory(root);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.RunAIJourneyView = api;
})(typeof window !== "undefined" ? window : globalThis, function (root) {
  "use strict";
  function createJourneyView(container, options = {}) {
    const events = root.RunAIJourneyContract.MAP_EVENTS;
    const target = options.errorTarget || container.parentNode;
    const timeline = root.RunAIJourneyFallback.createJourneyView(options.timelineContainer, {
      errorTarget: target, hiddenUntilError: false, reducedMotion: options.reducedMotion,
      attributions: ["© OpenStreetMap contributors"],
    });
    let map, player, plan, destroyed = false, mapFailed = false;
    const relay = event => options.onEvent?.(event.type, event.detail);
    Object.values(events).forEach(name => target.addEventListener(name, relay));
    function fail(event) {
      if (event?.detail?.fatal === false || mapFailed || destroyed) return;
      mapFailed = true;
      player?.destroy(); player = null;
      if (map) { map.off?.("load", ready); map.off?.("error", failed); map.remove(); map = null; }
      container.hidden = true;
    }
    function failed() {
      target.dispatchEvent(new root.CustomEvent(events.error, {
        bubbles: true, detail: { fatal: true, error: { code: "map_unavailable", message: "Carte indisponible ; timeline disponible." } },
      }));
    }
    function ready() {
      if (destroyed || mapFailed) return;
      player = root.RunAIJourneyPlayer.createJourneyView(container, { map, reducedMotion: options.reducedMotion });
      if (plan) player.setPlan(plan);
    }
    target.addEventListener(events.error, fail);
    container.addEventListener("webglcontextlost", failed, true);
    try {
      if (!root.maplibregl) throw new Error("MapLibre indisponible");
      map = new root.maplibregl.Map({ container, style: {
        version: 8, sources: { osm: { type: "raster", tileSize: 256,
          tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], attribution: "© OpenStreetMap contributors" } },
        layers: [{ id: "osm", type: "raster", source: "osm" }],
      } });
      map.on("error", failed);
      map.on("load", ready);
    } catch (_) { failed(); }
    return {
      setPlan(value) { plan = value; timeline.setPlan(value); player?.setPlan(value); },
      showChapter(id) { timeline.showChapter(id); player?.showChapter(id); },
      play() { if (player) player.play(); else timeline.play(); },
      pause() { player?.pause(); timeline.pause(); },
      seekKm(km) { if (player) player.seekKm(km); else timeline.seekKm(km); },
      destroy() {
        if (destroyed) return;
        destroyed = true;
        player?.destroy(); timeline.destroy();
        if (map) { map.off?.("load", ready); map.off?.("error", failed); map.remove(); }
        target.removeEventListener(events.error, fail);
        container.removeEventListener("webglcontextlost", failed, true);
        Object.values(events).forEach(name => target.removeEventListener(name, relay));
      },
    };
  }
  return { createJourneyView };
});
