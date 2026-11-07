/* JourneyPlan v1 contract for the map/chapter layer (mirrors runai/contracts/journey.py). Pure, Node-testable. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.RunAIJourneyContract = api;
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const SCHEMA_VERSION = "journey.v1";
  const CHAPTER_IDS = ["home", "departure_hub", "main_transport", "arrival_hotel", "bib_pickup", "race", "return_trip"];
  const STOP_KINDS = ["home", "station", "airport", "hotel", "bib_pickup", "race_start", "race_finish"];
  const SEGMENT_MODES = ["walk", "local", "train", "flight", "race"];
  const GEOMETRY_STATUS = ["verified", "approximate", "illustrative", "unavailable"];
  const DATA_MODES = ["live", "demo", "replay"];

  /*
   * Map/player interface implemented by C1/C2/C3, wired by E3, consumed by D1/D2:
   *   const view = createJourneyView(container, { reducedMotion });
   *   view.setPlan(plan)            // JourneyPlan v1; replaces any previous revision
   *   view.showChapter(chapterId)   // one of CHAPTER_IDS
   *   view.play() / view.pause()    // camera only, never the H agents
   *   view.seekKm(km)               // race chapter, existing RunAIFlyover
   *   view.destroy()
   * The container dispatches CustomEvents named in MAP_EVENTS with `detail`
   * { planRevision, chapterId?, state?, error? }.
   */
  const MAP_EVENTS = {
    ready: "runai:journey-ready",
    chapter: "runai:journey-chapter",
    playback: "runai:journey-playback",
    error: "runai:journey-error",
  };

  function validateJourneyPlan(plan) {
    const errors = [];
    if (!plan || plan.schema_version !== SCHEMA_VERSION) errors.push("schema_version");
    if (!DATA_MODES.includes(plan && plan.mode)) errors.push("mode");
    const stops = new Set();
    for (const stop of (plan && plan.stops) || []) {
      if (stops.has(stop.id)) errors.push(`duplicate stop ${stop.id}`);
      stops.add(stop.id);
      if (!STOP_KINDS.includes(stop.kind)) errors.push(`stop kind ${stop.id}`);
    }
    const segments = new Set();
    for (const seg of (plan && plan.segments) || []) {
      segments.add(seg.id);
      if (!SEGMENT_MODES.includes(seg.mode)) errors.push(`segment mode ${seg.id}`);
      if (!GEOMETRY_STATUS.includes(seg.geometry_status)) errors.push(`geometry_status ${seg.id}`);
      if ((seg.geometry_status === "unavailable") !== !(seg.geometry && seg.geometry.length)) {
        errors.push(`geometry ${seg.id}`);
      }
      for (const ref of [seg.from_stop_id, seg.to_stop_id]) {
        if (!stops.has(ref)) errors.push(`segment ${seg.id} -> ${ref}`);
      }
    }
    for (const chapter of (plan && plan.chapters) || []) {
      if (!CHAPTER_IDS.includes(chapter.id)) errors.push(`chapter ${chapter.id}`);
      for (const ref of chapter.stop_ids || []) if (!stops.has(ref)) errors.push(`chapter ${chapter.id} -> ${ref}`);
      for (const ref of chapter.segment_ids || []) if (!segments.has(ref)) errors.push(`chapter ${chapter.id} -> ${ref}`);
    }
    return errors;
  }

  return { SCHEMA_VERSION, CHAPTER_IDS, STOP_KINDS, SEGMENT_MODES, GEOMETRY_STATUS, DATA_MODES, MAP_EVENTS, validateJourneyPlan };
});
