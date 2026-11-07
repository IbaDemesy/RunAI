/* Pure JourneyPlan map data; load journey-contract.js and route.js first in browsers. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./journey-contract.js"), require("./route.js"));
  } else {
    root.RunAIJourneyData = factory(root.RunAIJourneyContract, root.RunAIRoute);
  }
})(typeof self !== "undefined" ? self : this, function (contract, route) {
  "use strict";

  function bounds(coordinates) {
    if (!coordinates.length) return null;
    const min = [Infinity, Infinity];
    const max = [-Infinity, -Infinity];
    for (const point of coordinates) {
      for (let axis = 0; axis < 2; axis++) {
        min[axis] = Math.min(min[axis], point[axis]);
        max[axis] = Math.max(max[axis], point[axis]);
      }
    }
    return [min, max];
  }

  function buildJourneyData(plan) {
    const errors = contract.validateJourneyPlan(plan);
    if (errors.length) {
      const error = new Error(`Invalid JourneyPlan: ${errors.join("; ")}`);
      error.errors = errors;
      throw error;
    }
    const chapters = plan.chapters || [];
    const chapterIds = (key, id) => chapters.filter((chapter) => (chapter[key] || []).includes(id)).map((chapter) => chapter.id);
    const stops = { type: "FeatureCollection", features: [] };
    const segments = { type: "FeatureCollection", features: [] };
    const unplaced = [];
    const unmapped = [];
    for (const stop of plan.stops || []) {
      const properties = {
        id: stop.id, kind: stop.kind, label: stop.label, confidence: stop.confidence,
        chapter_ids: chapterIds("stop_ids", stop.id),
      };
      if (stop.coords == null) {
        unplaced.push(properties);
      } else {
        stops.features.push({ type: "Feature", properties, geometry: { type: "Point", coordinates: [stop.coords.lon, stop.coords.lat] } });
      }
    }
    for (const segment of plan.segments || []) {
      const properties = {
        id: segment.id, mode: segment.mode, layer: segment.mode,
        geometry_status: segment.geometry_status, automation: segment.automation,
        from_stop_id: segment.from_stop_id, to_stop_id: segment.to_stop_id,
        chapter_ids: chapterIds("segment_ids", segment.id),
      };
      if (segment.geometry_status === "unavailable") {
        unmapped.push(properties);
      } else {
        segments.features.push({ type: "Feature", properties, geometry: { type: "LineString", coordinates: segment.geometry.map((point) => point.slice()) } });
      }
    }
    const coordinatesFor = (chapterId) => [
      ...stops.features.filter((feature) => chapterId === undefined || feature.properties.chapter_ids.includes(chapterId)).map((feature) => feature.geometry.coordinates),
      ...segments.features.filter((feature) => chapterId === undefined || feature.properties.chapter_ids.includes(chapterId)).flatMap((feature) => feature.geometry.coordinates),
    ];
    return {
      revision: plan.revision, mode: plan.mode, stops, segments, unplaced, unmapped,
      chapterBounds: Object.fromEntries(chapters.map((chapter) => [chapter.id, bounds(coordinatesFor(chapter.id))])),
      bounds: bounds(coordinatesFor()),
    };
  }

  function buildRaceLine(text, geometryStatus) {
    if (!contract.GEOMETRY_STATUS.includes(geometryStatus)) throw new Error(`Invalid geometry_status: ${geometryStatus}`);
    if (geometryStatus === "unavailable") return null;
    const feature = route.toGeoJson(route.parseTrack(text));
    feature.properties = { mode: "race", layer: "race", geometry_status: geometryStatus };
    return feature;
  }

  return { buildJourneyData, buildRaceLine };
});
