const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const R = require("../route.js");

const SAMPLE = fs.readFileSync(path.join(__dirname, "..", "samples", "lisbonne-collines-exemple.gpx"), "utf8");

const LINE = [
  { lon: 0, lat: 0, ele: 10 },
  { lon: 0, lat: 0.009, ele: 20 },
  { lon: 0, lat: 0.018, ele: 15 },
];

test("parses GPX track points with elevation and name", () => {
  const { name, points } = R.parseTrack(SAMPLE);
  assert.match(name, /exemple/);
  assert.ok(points.length > 100);
  assert.ok(R.hasElevation(points));
});

test("prefers track points over route points and tolerates prefixes", () => {
  const gpx = `<gpx><rte><rtept lat="1" lon="1"/></rte><trk><name>A &amp; B</name><trkseg>
    <gpx:trkpt lon="2.0" lat="48.0"><gpx:ele>35</gpx:ele></gpx:trkpt>
    <trkpt lat='48.001' lon='2.001'/></trkseg></trk></gpx>`;
  const { name, points } = R.parseTrack(gpx);
  assert.equal(name, "A & B");
  assert.deepEqual(points, [
    { lon: 2, lat: 48, ele: 35 },
    { lon: 2.001, lat: 48.001, ele: null },
  ]);
  assert.equal(R.hasElevation(points), false);
});

test("parses KML LineString coordinates", () => {
  const kml = `<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Semi</name>
    <Placemark><LineString><coordinates>-9.17,38.69,0 -9.16,38.70,0
    -9.15,38.70</coordinates></LineString></Placemark></Document></kml>`;
  const { name, points } = R.parseTrack(kml);
  assert.equal(name, "Semi");
  assert.equal(points.length, 3);
  assert.equal(points[2].ele, null);
});

test("rejects files without a usable line", () => {
  assert.throws(() => R.parseTrack("<gpx><wpt lat='1' lon='1'/></gpx>"), /at least two points/);
});

test("builds cumulative distance and climb with hysteresis", () => {
  const track = R.buildTrack(LINE, { smoothingM: 0 });
  assert.ok(Math.abs(track.totalM - 2001.5) < 2, track.totalM);
  assert.equal(track.gain, 10);
  assert.equal(track.loss, 5);
  assert.equal(track.minEle, 10);
  assert.equal(track.maxEle, 20);
  const noisy = R.buildTrack(LINE.map((p, i) => ({ ...p, ele: 10 + (i % 2) })), { smoothingM: 0 });
  assert.equal(noisy.gain, 0);
});

test("smooths DEM steps before computing climb", () => {
  const steps = Array.from({ length: 41 }, (_, i) => ({ lon: 0, lat: i * 0.00018, ele: i % 2 ? 14 : 10 }));
  assert.equal(R.buildTrack(steps, { smoothingM: 0 }).gain, 80);
  assert.ok(R.buildTrack(steps).gain < 5);
});

test("interpolates position and elevation along the track", () => {
  const track = R.buildTrack(LINE);
  const half = R.pointAt(track, track.cumulative[1] / 2);
  assert.ok(Math.abs(half.lat - 0.0045) < 1e-9);
  assert.ok(Math.abs(half.ele - 15) < 1e-9);
  assert.deepEqual(
    [R.pointAt(track, -5).lat, R.pointAt(track, 1e9).lat],
    [0, 0.018],
  );
});

test("places one marker per full kilometre", () => {
  const track = R.buildTrack(R.parseTrack(SAMPLE).points);
  const markers = R.kmMarkers(track);
  assert.equal(markers.length, Math.floor((track.totalM - 200) / 1000));
  assert.equal(markers[0].km, 1);
  assert.ok(Math.abs(markers[0].distance - 1000) < 1e-6);
});

test("computes bearings and smooths through north", () => {
  assert.ok(Math.abs(R.bearingDeg({ lon: 0, lat: 0 }, { lon: 0, lat: 1 })) < 1e-9);
  assert.ok(Math.abs(R.bearingDeg({ lon: 0, lat: 0 }, { lon: 1, lat: 0 }) - 90) < 1e-9);
  assert.ok(Math.abs(R.smoothAngle(350, 10, 0.5) - 0) < 1e-9);
  const track = R.buildTrack(LINE);
  assert.ok(Math.abs(R.lookAheadBearing(track, 500, 200)) < 1e-6);
});

test("decodes terrarium elevation and tile coordinates", () => {
  assert.equal(R.terrariumElevation(128, 0, 0), 0);
  assert.equal(R.terrariumElevation(128, 100, 128), 100.5);
  const tile = R.tileFor(-9.14, 38.715, 12, 512);
  assert.deepEqual([tile.x, tile.y, tile.z], [1944, 1569, 12]);
  assert.ok(tile.px >= 0 && tile.px < 512 && tile.py >= 0 && tile.py < 512);
});

test("exports GeoJSON and bounds", () => {
  const track = R.buildTrack(LINE);
  assert.deepEqual(R.toGeoJson(track).geometry.coordinates[1], [0, 0.009]);
  assert.deepEqual(R.bounds(LINE), [[0, 0], [0, 0.018]]);
});
