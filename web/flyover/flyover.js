/* RunAI flyover: MapLibre GL JS + Mapterhorn terrain, camera following a GPX/KML track. */
(function () {
  "use strict";

  const R = window.RunAIRoute;
  const params = new URLSearchParams(window.location.search);
  const SAMPLE_GPX = "samples/lisbonne-collines-exemple.gpx";
  const TERRAIN_TILES = "https://tiles.mapterhorn.com/{z}/{x}/{y}.webp";
  const TERRAIN_ATTRIBUTION = "<a href='https://mapterhorn.com/attribution' target='_blank'>© Mapterhorn</a>";
  const TERRAIN_SAMPLE_ZOOM = 12;
  const COLOR_DONE = "#ff5a1f";
  const COLOR_TODO = "#ffd54a";
  const FOLLOW_PITCH = 62;
  const FOLLOW_ZOOM = 15.2;

  const $ = (id) => document.getElementById(id);
  const ui = {
    name: $("track-name"),
    disclaimer: $("disclaimer"),
    distance: $("stat-distance"),
    climb: $("stat-climb"),
    ele: $("stat-ele"),
    source: $("stat-source"),
    play: $("play"),
    restart: $("restart"),
    overview: $("overview"),
    duration: $("duration"),
    basemap: $("basemap"),
    exaggeration: $("exaggeration"),
    exaggerationValue: $("exaggeration-value"),
    file: $("file"),
    status: $("status"),
    readout: $("readout"),
    profile: $("profile"),
  };

  const state = {
    track: null,
    distance: 0,
    playing: false,
    durationS: Number(params.get("duration")) || 60,
    bearing: 0,
    lastFrame: null,
    markers: [],
    runner: null,
  };

  const km = (meters, digits) => (meters / 1000).toFixed(digits === undefined ? 2 : digits).replace(".", ",");
  const setStatus = (text) => {
    ui.status.textContent = text || "";
  };

  if (!window.maplibregl) {
    setStatus("MapLibre GL JS n'a pas pu être chargé (réseau ?).");
    return;
  }

  const exaggeration = Number(params.get("exaggeration")) || 1.5;
  ui.exaggeration.value = String(exaggeration);
  ui.exaggerationValue.textContent = exaggeration.toFixed(1);
  if ([...ui.duration.options].some((option) => Number(option.value) === state.durationS)) {
    ui.duration.value = String(state.durationS);
  }
  const initialBasemap = params.get("basemap") === "satellite" ? "satellite" : "osm";
  ui.basemap.value = initialBasemap;

  const map = new maplibregl.Map({
    container: "map",
    center: [-9.14, 38.715],
    zoom: 12,
    pitch: 50,
    maxPitch: 80,
    attributionControl: false,
    canvasContextAttributes: { preserveDrawingBuffer: params.has("capture") },
    style: {
      version: 8,
      sources: {
        osm: {
          type: "raster",
          tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
          tileSize: 256,
          maxzoom: 19,
          attribution: "© <a href='https://www.openstreetmap.org/copyright' target='_blank'>OpenStreetMap</a> contributors",
        },
        satellite: {
          type: "raster",
          tiles: ["https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2020_3857/default/g/{z}/{y}/{x}.jpg"],
          tileSize: 256,
          maxzoom: 15,
          attribution:
            "<a href='https://s2maps.eu' target='_blank'>Sentinel-2 cloudless 2020</a> by EOX IT Services GmbH " +
            "(Contains modified Copernicus Sentinel data 2020), CC BY-NC-SA 4.0",
        },
        terrain: {
          type: "raster-dem",
          tiles: [TERRAIN_TILES],
          tileSize: 512,
          maxzoom: 15,
          encoding: "terrarium",
          attribution: TERRAIN_ATTRIBUTION,
        },
        hillshade: {
          type: "raster-dem",
          tiles: [TERRAIN_TILES],
          tileSize: 512,
          maxzoom: 15,
          encoding: "terrarium",
          attribution: TERRAIN_ATTRIBUTION,
        },
      },
      layers: [
        { id: "osm", type: "raster", source: "osm", layout: { visibility: initialBasemap === "osm" ? "visible" : "none" } },
        {
          id: "satellite",
          type: "raster",
          source: "satellite",
          layout: { visibility: initialBasemap === "satellite" ? "visible" : "none" },
        },
        {
          id: "hillshade",
          type: "hillshade",
          source: "hillshade",
          paint: { "hillshade-shadow-color": "#473B24", "hillshade-exaggeration": 0.35 },
        },
      ],
      terrain: { source: "terrain", exaggeration },
      sky: {
        "sky-color": "#7fb2e5",
        "horizon-color": "#dfe9f3",
        "fog-color": "#e8eef5",
        "sky-horizon-blend": 0.6,
        "horizon-fog-blend": 0.7,
        "fog-ground-blend": 0.6,
      },
    },
  });
  map.addControl(new maplibregl.AttributionControl({ compact: false }), "bottom-right");
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
  map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
  map.on("error", (event) => {
    if (event && event.error) console.warn("MapLibre:", event.error.message || event.error);
  });

  // ---- Elevation fallback: decode Mapterhorn terrarium tiles when the file has no <ele>.
  async function sampleTerrain(points) {
    const tiles = new Map();
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 512;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    async function tilePixels(tile) {
      const key = `${tile.z}/${tile.x}/${tile.y}`;
      if (!tiles.has(key)) {
        tiles.set(
          key,
          (async () => {
            const url = TERRAIN_TILES.replace("{z}", tile.z).replace("{x}", tile.x).replace("{y}", tile.y);
            const response = await fetch(url);
            if (!response.ok) throw new Error(`tuile ${key} : HTTP ${response.status}`);
            const bitmap = await createImageBitmap(await response.blob());
            context.clearRect(0, 0, 512, 512);
            context.drawImage(bitmap, 0, 0);
            return context.getImageData(0, 0, 512, 512).data;
          })(),
        );
      }
      return tiles.get(key);
    }
    const result = [];
    for (const point of points) {
      const tile = R.tileFor(point.lon, point.lat, TERRAIN_SAMPLE_ZOOM, 512);
      const data = await tilePixels(tile);
      const offset = (tile.py * 512 + tile.px) * 4;
      result.push({ ...point, ele: R.terrariumElevation(data[offset], data[offset + 1], data[offset + 2]) });
    }
    return result;
  }

  // ---- Elevation profile.
  function drawProfile() {
    const canvas = ui.profile;
    const ratio = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const track = state.track;
    if (!track || !Number.isFinite(track.minEle)) return;

    const pad = { left: 44, right: 14, top: 26, bottom: 22 };
    const span = Math.max(20, track.maxEle - track.minEle);
    const low = track.minEle - span * 0.1;
    const high = track.maxEle + span * 0.15;
    const x = (d) => pad.left + (d / track.totalM) * (width - pad.left - pad.right);
    const y = (ele) => height - pad.bottom - ((ele - low) / (high - low)) * (height - pad.top - pad.bottom);

    ctx.font = "11px system-ui, sans-serif";
    ctx.fillStyle = "#a9b2c3";
    ctx.strokeStyle = "rgba(255,255,255,0.08)";
    ctx.lineWidth = 1;
    const kmStep = track.totalM > 25000 ? 5000 : track.totalM > 12000 ? 2000 : 1000;
    for (let d = 0; d <= track.totalM; d += kmStep) {
      ctx.beginPath();
      ctx.moveTo(x(d), pad.top);
      ctx.lineTo(x(d), height - pad.bottom);
      ctx.stroke();
      ctx.fillText(`${Math.round(d / 1000)} km`, x(d) - 10, height - 6);
    }
    for (const ele of [track.minEle, track.maxEle]) {
      ctx.fillText(`${Math.round(ele)} m`, 4, y(ele) + 4);
    }

    const path = new Path2D();
    path.moveTo(x(0), height - pad.bottom);
    track.points.forEach((point, i) => path.lineTo(x(track.cumulative[i]), y(point.ele)));
    path.lineTo(x(track.totalM), height - pad.bottom);
    path.closePath();

    const split = x(state.distance);
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, split, height);
    ctx.clip();
    ctx.fillStyle = "rgba(255, 90, 31, 0.55)";
    ctx.fill(path);
    ctx.restore();
    ctx.save();
    ctx.beginPath();
    ctx.rect(split, 0, width - split, height);
    ctx.clip();
    ctx.fillStyle = "rgba(255, 213, 74, 0.45)";
    ctx.fill(path);
    ctx.restore();

    const here = R.pointAt(track, state.distance);
    ctx.strokeStyle = "#fff";
    ctx.beginPath();
    ctx.moveTo(split, pad.top - 6);
    ctx.lineTo(split, height - pad.bottom);
    ctx.stroke();
    ctx.fillStyle = "#fff";
    ctx.beginPath();
    ctx.arc(split, y(here.ele), 4, 0, Math.PI * 2);
    ctx.fill();
  }

  function profileDistance(event) {
    const rect = ui.profile.getBoundingClientRect();
    const usable = rect.width - 44 - 14;
    return Math.max(0, Math.min(1, (event.clientX - rect.left - 44) / usable)) * state.track.totalM;
  }

  ui.profile.addEventListener("pointerdown", (event) => {
    if (!state.track) return;
    ui.profile.setPointerCapture(event.pointerId);
    seek(profileDistance(event), { follow: true });
  });
  ui.profile.addEventListener("pointermove", (event) => {
    if (state.track && event.buttons & 1) seek(profileDistance(event), { follow: true });
  });
  window.addEventListener("resize", drawProfile);

  // ---- Route rendering.
  function setProgressPaint() {
    if (!map.getLayer("route-line")) return;
    const fraction = state.track ? Math.min(0.999999, Math.max(0.000001, state.distance / state.track.totalM)) : 0;
    map.setPaintProperty("route-line", "line-gradient", [
      "step",
      ["line-progress"],
      COLOR_DONE,
      fraction,
      COLOR_TODO,
    ]);
  }

  function markerElement(className, text) {
    const element = document.createElement("div");
    element.className = className;
    if (text) element.textContent = text;
    return element;
  }

  function addMarkers(track) {
    state.markers.forEach((marker) => marker.remove());
    state.markers = [];
    const start = track.points[0];
    const finish = track.points[track.points.length - 1];
    const loop = R.distanceM(start, finish) < 60;
    for (const marker of R.kmMarkers(track, 1000)) {
      state.markers.push(
        new maplibregl.Marker({ element: markerElement("marker-km", String(Math.round(marker.km))) })
          .setLngLat([marker.lon, marker.lat])
          .addTo(map),
      );
    }
    state.markers.push(
      new maplibregl.Marker({ element: markerElement("marker-flag marker-start", loop ? "Départ / Arrivée" : "Départ"), anchor: "bottom" })
        .setLngLat([start.lon, start.lat])
        .addTo(map),
    );
    if (!loop) {
      state.markers.push(
        new maplibregl.Marker({ element: markerElement("marker-flag marker-finish", "Arrivée"), anchor: "bottom" })
          .setLngLat([finish.lon, finish.lat])
          .addTo(map),
      );
    }
    if (!state.runner) state.runner = new maplibregl.Marker({ element: markerElement("marker-runner") });
    state.runner.setLngLat([start.lon, start.lat]).addTo(map);
  }

  function showRoute(track) {
    const data = R.toGeoJson(track);
    if (map.getSource("route")) {
      map.getSource("route").setData(data);
    } else {
      map.addSource("route", { type: "geojson", data, lineMetrics: true });
      map.addLayer({
        id: "route-casing",
        type: "line",
        source: "route",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#ffffff", "line-width": ["interpolate", ["linear"], ["zoom"], 11, 4, 16, 11], "line-opacity": 0.9 },
      });
      map.addLayer({
        id: "route-line",
        type: "line",
        source: "route",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-width": ["interpolate", ["linear"], ["zoom"], 11, 2.5, 16, 7], "line-color": COLOR_TODO },
      });
    }
    addMarkers(track);
  }

  // ---- Camera and playback.
  function overview() {
    if (!state.track) return;
    pause();
    map.fitBounds(R.bounds(state.track.points), {
      padding: { top: 60, bottom: 40, left: 300, right: 60 },
      pitch: 55,
      bearing: -20,
      duration: 1200,
    });
  }

  function follow(immediate) {
    const track = state.track;
    const here = R.pointAt(track, state.distance);
    const target = R.lookAheadBearing(track, state.distance, 250);
    if (target !== null) state.bearing = immediate ? target : R.smoothAngle(state.bearing, target, immediate === false ? 0.06 : 0.25);
    map.jumpTo({ center: [here.lon, here.lat], bearing: state.bearing });
  }

  function updatePosition() {
    const track = state.track;
    const here = R.pointAt(track, state.distance);
    state.runner.setLngLat([here.lon, here.lat]);
    const ele = Number.isFinite(here.ele) ? ` · ${Math.round(here.ele)} m` : "";
    ui.readout.textContent = `km ${km(state.distance)} / ${km(track.totalM)}${ele}`;
    setProgressPaint();
    drawProfile();
  }

  function seek(distance, options) {
    if (!state.track) return;
    state.distance = Math.max(0, Math.min(state.track.totalM, distance));
    if (options && options.follow) {
      if (!state.playing) map.jumpTo({ pitch: FOLLOW_PITCH, zoom: Math.max(map.getZoom(), FOLLOW_ZOOM - 1) });
      follow(true);
    }
    updatePosition();
  }

  function frame(timestamp) {
    if (!state.playing) return;
    const dt = state.lastFrame === null ? 0 : Math.min(0.1, (timestamp - state.lastFrame) / 1000);
    state.lastFrame = timestamp;
    state.distance = Math.min(state.track.totalM, state.distance + (state.track.totalM / state.durationS) * dt);
    follow(false);
    updatePosition();
    if (state.distance >= state.track.totalM) {
      pause();
      setTimeout(overview, 800);
      return;
    }
    requestAnimationFrame(frame);
  }

  function play() {
    if (!state.track || state.playing) return;
    if (state.distance >= state.track.totalM) state.distance = 0;
    state.playing = true;
    state.lastFrame = null;
    ui.play.textContent = "❚❚ Pause";
    const here = R.pointAt(state.track, state.distance);
    state.bearing = R.lookAheadBearing(state.track, state.distance, 250) || map.getBearing();
    map.easeTo({ center: [here.lon, here.lat], zoom: FOLLOW_ZOOM, pitch: FOLLOW_PITCH, bearing: state.bearing, duration: 1500 });
    map.once("moveend", () => requestAnimationFrame(frame));
  }

  function pause() {
    state.playing = false;
    ui.play.textContent = "▶ Lecture";
  }

  // ---- Loading.
  async function loadText(text, label) {
    pause();
    setStatus("");
    const parsed = R.parseTrack(text);
    let points = parsed.points;
    let source = "fichier (GPX/KML)";
    if (!R.hasElevation(points)) {
      setStatus("Pas d'altitude dans le fichier : lecture du relief Mapterhorn…");
      points = await sampleTerrain(points);
      source = `Mapterhorn (z${TERRAIN_SAMPLE_ZOOM})`;
      setStatus("");
    }
    const track = R.buildTrack(points);
    state.track = track;
    state.distance = 0;
    ui.name.textContent = parsed.name || label || "Parcours sans nom";
    ui.disclaimer.hidden = !/exemple/i.test(`${parsed.name} ${label || ""}`);
    ui.distance.textContent = `${km(track.totalM)} km`;
    ui.climb.textContent = `≈ +${Math.round(track.gain)} m / −${Math.round(track.loss)} m`;
    ui.ele.textContent = `${Math.round(track.minEle)}–${Math.round(track.maxEle)} m`;
    ui.source.textContent = source;
    [ui.play, ui.restart, ui.overview].forEach((button) => (button.disabled = false));
    showRoute(track);
    updatePosition();
    overview();
    return track;
  }

  async function loadUrl(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP ${response.status} sur ${url}`);
    return loadText(await response.text(), decodeURIComponent(url.split("/").pop()));
  }

  async function loadFile(file) {
    try {
      await loadText(await file.text(), file.name);
    } catch (error) {
      setStatus(`Fichier illisible : ${error.message}`);
    }
  }

  ui.play.addEventListener("click", () => (state.playing ? pause() : play()));
  ui.restart.addEventListener("click", () => {
    pause();
    seek(0, { follow: true });
  });
  ui.overview.addEventListener("click", overview);
  ui.duration.addEventListener("change", () => (state.durationS = Number(ui.duration.value)));
  ui.basemap.addEventListener("change", () => {
    map.setLayoutProperty("osm", "visibility", ui.basemap.value === "osm" ? "visible" : "none");
    map.setLayoutProperty("satellite", "visibility", ui.basemap.value === "satellite" ? "visible" : "none");
  });
  ui.exaggeration.addEventListener("input", () => {
    const value = Number(ui.exaggeration.value);
    ui.exaggerationValue.textContent = value.toFixed(1);
    map.setTerrain({ source: "terrain", exaggeration: value });
  });
  ui.file.addEventListener("change", () => ui.file.files[0] && loadFile(ui.file.files[0]));
  window.addEventListener("dragover", (event) => {
    event.preventDefault();
    document.body.classList.add("dragging");
  });
  window.addEventListener("dragleave", () => document.body.classList.remove("dragging"));
  window.addEventListener("drop", (event) => {
    event.preventDefault();
    document.body.classList.remove("dragging");
    if (event.dataTransfer.files[0]) loadFile(event.dataTransfer.files[0]);
  });
  window.addEventListener("keydown", (event) => {
    if (!state.track || event.target.matches("input, select")) return;
    if (event.code === "Space") {
      event.preventDefault();
      state.playing ? pause() : play();
    } else if (event.code === "ArrowRight" || event.code === "ArrowLeft") {
      seek(state.distance + (event.code === "ArrowRight" ? 500 : -500), { follow: true });
    }
  });

  map.on("load", async () => {
    const url = params.get("gpx") || SAMPLE_GPX;
    try {
      await loadUrl(url);
      if (params.has("km")) seek(Number(params.get("km")) * 1000, { follow: true });
      if (params.get("autoplay") === "1") play();
    } catch (error) {
      const hint = window.location.protocol === "file:" ? " Ouvrez la page via un serveur local (voir README) ou choisissez un fichier." : "";
      setStatus(`Impossible de charger ${url} : ${error.message}.${hint}`);
    }
  });

  // Small API for the RunAI app or voice commands (« montre le km 7 »).
  window.RunAIFlyover = {
    map,
    loadText,
    loadUrl,
    play,
    pause,
    overview,
    seekKm: (value) => seek(value * 1000, { follow: true }),
    setDuration: (seconds) => (state.durationS = seconds),
    get state() {
      return { distanceM: state.distance, totalM: state.track ? state.track.totalM : 0, playing: state.playing };
    },
  };
})();
