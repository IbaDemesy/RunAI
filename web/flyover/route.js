/* Pure track helpers for the RunAI flyover. No DOM or map dependency, so they run in Node tests. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.RunAIRoute = api;
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const EARTH_RADIUS_M = 6371008.8;
  const toRad = (deg) => (deg * Math.PI) / 180;
  const toDeg = (rad) => (rad * 180) / Math.PI;

  function decodeEntities(text) {
    return text
      .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"')
      .replace(/&apos;/g, "'")
      .replace(/&#(\d+);/g, (_, code) => String.fromCharCode(Number(code)))
      .replace(/&amp;/g, "&")
      .trim();
  }

  function attribute(attrs, name) {
    const match = new RegExp(`\\b${name}\\s*=\\s*["']([^"']+)["']`).exec(attrs);
    return match ? Number(match[1]) : NaN;
  }

  function firstName(text) {
    const match = /<(?:\w+:)?name>([\s\S]*?)<\/(?:\w+:)?name>/.exec(text);
    return match ? decodeEntities(match[1]) : "";
  }

  function parseGpxPoints(text, tag) {
    const points = [];
    const pattern = new RegExp(`<(?:\\w+:)?${tag}\\b([^>]*?)(?:\\/>|>([\\s\\S]*?)<\\/(?:\\w+:)?${tag}>)`, "g");
    let match;
    while ((match = pattern.exec(text)) !== null) {
      const lat = attribute(match[1], "lat");
      const lon = attribute(match[1], "lon");
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
      const eleMatch = /<(?:\w+:)?ele>\s*([-+0-9.eE]+)\s*</.exec(match[2] || "");
      points.push({ lon, lat, ele: eleMatch ? Number(eleMatch[1]) : null });
    }
    return points;
  }

  function parseGpx(text) {
    // Prefer track points; route points only when the file has no track.
    const track = parseGpxPoints(text, "trkpt");
    return { name: firstName(text), points: track.length ? track : parseGpxPoints(text, "rtept") };
  }

  function parseKml(text) {
    const points = [];
    const lines = /<(?:\w+:)?LineString\b[\s\S]*?<(?:\w+:)?coordinates>([\s\S]*?)<\/(?:\w+:)?coordinates>/g;
    let match;
    while ((match = lines.exec(text)) !== null) {
      for (const tuple of match[1].trim().split(/\s+/)) {
        const [lon, lat, ele] = tuple.split(",").map(Number);
        if (Number.isFinite(lat) && Number.isFinite(lon)) {
          points.push({ lon, lat, ele: Number.isFinite(ele) && tuple.split(",").length > 2 ? ele : null });
        }
      }
    }
    if (points.length === 0) {
      const coords = /<gx:coord>\s*([^<]+)<\/gx:coord>/g;
      while ((match = coords.exec(text)) !== null) {
        const [lon, lat, ele] = match[1].trim().split(/\s+/).map(Number);
        if (Number.isFinite(lat) && Number.isFinite(lon)) {
          points.push({ lon, lat, ele: Number.isFinite(ele) ? ele : null });
        }
      }
    }
    return { name: firstName(text), points };
  }

  function parseTrack(text) {
    const parsed = /<(?:\w+:)?kml\b/.test(text) ? parseKml(text) : parseGpx(text);
    const points = parsed.points.filter((point, i, all) => {
      const previous = all[i - 1];
      return !previous || previous.lon !== point.lon || previous.lat !== point.lat;
    });
    if (points.length < 2) {
      throw new Error("No usable route: at least two points are required (trkpt, rtept or LineString).");
    }
    return { name: parsed.name, points };
  }

  function distanceM(a, b) {
    const dLat = toRad(b.lat - a.lat);
    const dLon = toRad(b.lon - a.lon);
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2;
    return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)));
  }

  function bearingDeg(a, b) {
    const y = Math.sin(toRad(b.lon - a.lon)) * Math.cos(toRad(b.lat));
    const x =
      Math.cos(toRad(a.lat)) * Math.sin(toRad(b.lat)) -
      Math.sin(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.cos(toRad(b.lon - a.lon));
    return (toDeg(Math.atan2(y, x)) + 360) % 360;
  }

  function hasElevation(points) {
    return points.every((point) => Number.isFinite(point.ele));
  }

  // Elevation gain/loss with a hysteresis threshold to ignore DEM/GPS noise.
  function climb(points, thresholdM) {
    let gain = 0;
    let loss = 0;
    let reference = points[0].ele;
    for (const point of points) {
      const delta = point.ele - reference;
      if (delta >= thresholdM) {
        gain += delta;
        reference = point.ele;
      } else if (delta <= -thresholdM) {
        loss -= delta;
        reference = point.ele;
      }
    }
    return { gain, loss };
  }

  // Moving average over a distance window, to damp DEM steps before computing climb.
  function smoothElevations(points, cumulative, windowM) {
    const half = windowM / 2;
    const result = [];
    let low = 0;
    let high = 0;
    let sum = 0;
    for (let i = 0; i < points.length; i += 1) {
      while (high < points.length && cumulative[high] <= cumulative[i] + half) sum += points[high++].ele;
      while (cumulative[low] < cumulative[i] - half) sum -= points[low++].ele;
      result.push({ ...points[i], ele: sum / (high - low) });
    }
    return result;
  }

  function buildTrack(points, options) {
    const thresholdM = (options && options.climbThresholdM) || 3;
    const smoothingM = options && options.smoothingM !== undefined ? options.smoothingM : 100;
    const cumulative = [0];
    for (let i = 1; i < points.length; i += 1) {
      cumulative.push(cumulative[i - 1] + distanceM(points[i - 1], points[i]));
    }
    const track = { points, cumulative, totalM: cumulative[cumulative.length - 1] };
    if (hasElevation(points)) {
      const eles = points.map((point) => point.ele);
      const smoothed = smoothingM > 0 ? smoothElevations(points, cumulative, smoothingM) : points;
      Object.assign(track, { minEle: Math.min(...eles), maxEle: Math.max(...eles) }, climb(smoothed, thresholdM));
    }
    return track;
  }

  function segmentIndex(track, distance) {
    const { cumulative } = track;
    let low = 0;
    let high = cumulative.length - 1;
    while (high - low > 1) {
      const mid = (low + high) >> 1;
      if (cumulative[mid] <= distance) low = mid;
      else high = mid;
    }
    return low;
  }

  function pointAt(track, distance) {
    const d = Math.max(0, Math.min(track.totalM, distance));
    const i = segmentIndex(track, d);
    const a = track.points[i];
    const b = track.points[Math.min(i + 1, track.points.length - 1)];
    const length = track.cumulative[i + 1] - track.cumulative[i] || 1;
    const t = Math.max(0, Math.min(1, (d - track.cumulative[i]) / length));
    const ele = Number.isFinite(a.ele) && Number.isFinite(b.ele) ? a.ele + (b.ele - a.ele) * t : null;
    return { lon: a.lon + (b.lon - a.lon) * t, lat: a.lat + (b.lat - a.lat) * t, ele, index: i, distance: d };
  }

  function kmMarkers(track, stepM) {
    const step = stepM || 1000;
    const markers = [];
    for (let d = step; d < track.totalM - step * 0.2; d += step) {
      markers.push({ km: Math.round(d / 100) / 10, ...pointAt(track, d) });
    }
    return markers;
  }

  function lookAheadBearing(track, distance, aheadM) {
    const from = pointAt(track, distance - (aheadM || 200) * 0.25);
    const to = pointAt(track, distance + (aheadM || 200));
    return from.lon === to.lon && from.lat === to.lat ? null : bearingDeg(from, to);
  }

  function smoothAngle(current, target, factor) {
    const delta = ((target - current + 540) % 360) - 180;
    return (current + delta * factor + 360) % 360;
  }

  function terrariumElevation(r, g, b) {
    return r * 256 + g + b / 256 - 32768;
  }

  function tileFor(lon, lat, zoom, tileSize) {
    const n = 2 ** zoom;
    const x = ((lon + 180) / 360) * n;
    const latRad = toRad(Math.max(-85.0511, Math.min(85.0511, lat)));
    const y = ((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) * n;
    const size = tileSize || 512;
    return {
      x: Math.floor(x),
      y: Math.floor(y),
      z: zoom,
      px: Math.min(size - 1, Math.floor((x - Math.floor(x)) * size)),
      py: Math.min(size - 1, Math.floor((y - Math.floor(y)) * size)),
    };
  }

  function bounds(points) {
    const lons = points.map((point) => point.lon);
    const lats = points.map((point) => point.lat);
    return [
      [Math.min(...lons), Math.min(...lats)],
      [Math.max(...lons), Math.max(...lats)],
    ];
  }

  function toGeoJson(track) {
    return {
      type: "Feature",
      properties: {},
      geometry: { type: "LineString", coordinates: track.points.map((point) => [point.lon, point.lat]) },
    };
  }

  return {
    parseTrack,
    distanceM,
    bearingDeg,
    hasElevation,
    buildTrack,
    pointAt,
    kmMarkers,
    lookAheadBearing,
    smoothAngle,
    terrariumElevation,
    tileFor,
    bounds,
    toGeoJson,
  };
});
