const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const J = require("../../web/flyover/journey-contract.js");
const D = require("../../web/flyover/journey-data.js");

for (const directory of ["../../runai/contracts/fixtures", "../fixtures/journey"]) {
  const root = path.resolve(__dirname, directory);
  for (const file of fs.readdirSync(root).filter((name) => /^journey_.*\.json$/.test(name))) {
    test(`${directory}/${file}: Python planner contract maps without invented coordinates`, () => {
      const plan = JSON.parse(fs.readFileSync(path.join(root, file), "utf8"));
      const original = JSON.stringify(plan);
      assert.deepEqual(J.validateJourneyPlan(plan), []);
      const data = D.buildJourneyData(plan);
      assert.deepEqual(data.stops.features.map((f) => f.properties.id), plan.stops.filter((s) => s.coords).map((s) => s.id));
      assert.deepEqual(data.unplaced.map((s) => s.id), plan.stops.filter((s) => !s.coords).map((s) => s.id));
      for (const feature of data.stops.features) {
        const stop = plan.stops.find((s) => s.id === feature.properties.id);
        assert.deepEqual(feature.geometry.coordinates, [stop.coords.lon, stop.coords.lat]);
      }
      assert.deepEqual(data.segments.features.map((f) => f.properties.id), plan.segments.filter((s) => s.geometry_status !== "unavailable" && s.geometry).map((s) => s.id));
      for (const feature of data.segments.features) {
        const segment = plan.segments.find((s) => s.id === feature.properties.id);
        assert.deepEqual(feature.geometry.coordinates, segment.geometry);
        for (const key of ["from_stop_id", "to_stop_id"]) {
          assert.equal(feature.properties[key], segment[key]);
          assert.ok(plan.stops.some((s) => s.id === segment[key]));
        }
      }
      assert.equal(JSON.stringify(plan), original);
    });
  }
}
