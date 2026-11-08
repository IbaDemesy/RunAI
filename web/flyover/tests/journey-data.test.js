const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const D = require("../journey-data.js");
const R = require("../route.js");

const FIXTURES = path.join(__dirname, "..", "..", "..", "runai", "contracts", "fixtures");
const load = (name) => JSON.parse(fs.readFileSync(path.join(FIXTURES, `journey_${name}.json`), "utf8"));

for (const [name, placed, mapped] of [["train", 7, 6], ["flight", 7, 7], ["incomplete", 2, 0]]) {
  test(`${name} maps only supplied stops and geometry without mutation`, () => {
    const plan = load(name);
    const original = JSON.stringify(plan);
    const data = D.buildJourneyData(plan);
    assert.equal(data.revision, plan.revision);
    assert.equal(data.mode, plan.mode);
    assert.equal(data.stops.type, "FeatureCollection");
    assert.equal(data.segments.type, "FeatureCollection");
    assert.equal(data.stops.features.length, placed);
    assert.equal(data.segments.features.length, mapped);
    for (const feature of data.stops.features) {
      const stop = plan.stops.find((item) => item.id === feature.properties.id);
      assert.equal(feature.geometry.type, "Point");
      assert.deepEqual(feature.geometry.coordinates, [stop.coords.lon, stop.coords.lat]);
      for (const key of ["id", "kind", "label", "confidence"]) assert.equal(feature.properties[key], stop[key]);
      assert.deepEqual(feature.properties.chapter_ids, plan.chapters.filter((c) => c.stop_ids.includes(stop.id)).map((c) => c.id));
    }
    for (const feature of data.segments.features) {
      const segment = plan.segments.find((item) => item.id === feature.properties.id);
      assert.equal(feature.geometry.type, "LineString");
      assert.deepEqual(feature.geometry.coordinates, segment.geometry);
      for (const key of ["id", "mode", "geometry_status", "automation", "from_stop_id", "to_stop_id"]) assert.equal(feature.properties[key], segment[key]);
      assert.equal(feature.properties.layer, segment.mode);
    }
    const inputCoordinates = new Set([
      ...plan.stops.filter((s) => s.coords).map((s) => JSON.stringify([s.coords.lon, s.coords.lat])),
      ...plan.segments.flatMap((s) => s.geometry || []).map((p) => JSON.stringify(p)),
    ]);
    const outputCoordinates = [
      ...data.stops.features.map((f) => f.geometry.coordinates),
      ...data.segments.features.flatMap((f) => f.geometry.coordinates),
    ];
    for (const coordinate of outputCoordinates) assert.ok(inputCoordinates.has(JSON.stringify(coordinate)));
    assert.equal(JSON.stringify(plan), original);
  });
}

test("all five transport modes have distinct layers", () => {
  const features = ["train", "flight"].flatMap((name) => D.buildJourneyData(load(name)).segments.features);
  assert.deepEqual([...new Set(features.map((f) => f.properties.layer))].sort(), ["flight", "local", "race", "train", "walk"]);
});

test("incomplete stops and segments remain explicitly unmapped, with null empty chapter bounds", () => {
  const plan = load("incomplete");
  const data = D.buildJourneyData(plan);
  assert.deepEqual(data.unplaced.map((s) => s.id), plan.stops.filter((s) => s.coords === null).map((s) => s.id));
  assert.ok(data.unplaced.every((s) => s.label && s.kind));
  assert.deepEqual(data.unmapped.map((s) => s.id), plan.segments.map((s) => s.id));
  for (const id of ["departure_hub", "main_transport", "arrival_hotel", "bib_pickup", "return_trip"]) assert.equal(data.chapterBounds[id], null);
});

test("bounds include chapter stops and segment interiors, not unreferenced stops", () => {
  const plan = load("train");
  const segment = plan.segments[0];
  segment.geometry = [[-10, -20], [30, 40]];
  segment.geometry_status = "approximate";
  plan.chapters = [{ id: "main_transport", stop_ids: [], segment_ids: [segment.id] }];
  const data = D.buildJourneyData(plan);
  assert.deepEqual(data.chapterBounds.main_transport, [[-10, -20], [30, 40]]);
  assert.equal(data.segments.features[0].properties.geometry_status, "approximate");
  const coordinates = [...data.stops.features.map((f) => f.geometry.coordinates), ...data.segments.features.flatMap((f) => f.geometry.coordinates)];
  assert.deepEqual(data.bounds, [
    [Math.min(...coordinates.map((p) => p[0])), Math.min(...coordinates.map((p) => p[1]))],
    [Math.max(...coordinates.map((p) => p[0])), Math.max(...coordinates.map((p) => p[1]))],
  ]);
});

test("empty valid plan has no layers or fallback bounds", () => {
  const plan = load("train");
  plan.stops = [];
  plan.segments = [];
  plan.chapters = [{ id: "home", stop_ids: [], segment_ids: [] }];
  const data = D.buildJourneyData(plan);
  assert.deepEqual(data.stops.features, []);
  assert.deepEqual(data.segments.features, []);
  assert.deepEqual(data.unplaced, []);
  assert.deepEqual(data.unmapped, []);
  assert.equal(data.bounds, null);
  assert.equal(data.chapterBounds.home, null);
});

test("invalid plans throw all contract errors before returning data", () => {
  const plan = load("train");
  plan.mode = "fake";
  plan.segments[0].to_stop_id = "missing";
  assert.throws(() => D.buildJourneyData(plan), (error) => {
    assert.match(error.message, /Invalid JourneyPlan:.*mode.*missing/);
    assert.deepEqual(error.errors, ["mode", `segment ${plan.segments[0].id} -> missing`]);
    return true;
  });
  assert.throws(() => D.buildJourneyData(null), /schema_version.*mode/);
});

test("race helper reuses GPX and KML parsing, retaining caller status", () => {
  const sample = fs.readFileSync(path.join(__dirname, "..", "samples", "lisbonne-collines-exemple.gpx"), "utf8");
  for (const text of [sample, "<kml><LineString><coordinates>1,2 3,4</coordinates></LineString></kml>"]) {
    const feature = D.buildRaceLine(text, "verified");
    assert.deepEqual(feature.geometry, R.toGeoJson(R.parseTrack(text)).geometry);
    assert.deepEqual(feature.properties, { mode: "race", layer: "race", geometry_status: "verified" });
  }
  assert.equal(D.buildRaceLine("", "unavailable"), null);
  assert.throws(() => D.buildRaceLine("", "verified"), /at least two points/);
  assert.throws(() => D.buildRaceLine(sample, "fake"), /Invalid geometry_status/);
});

test("browser UMD exposes the same adapter using browser dependencies", () => {
  const context = vm.createContext({});
  for (const file of ["journey-contract.js", "route.js", "journey-data.js"]) vm.runInContext(fs.readFileSync(path.join(__dirname, "..", file), "utf8"), context);
  assert.equal(JSON.stringify(context.RunAIJourneyData.buildJourneyData(load("flight"))), JSON.stringify(D.buildJourneyData(load("flight"))));
});
