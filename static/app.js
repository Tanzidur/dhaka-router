"use strict";

const $ = (id) => document.getElementById(id);
const COLORS = ["#1f5fbf", "#d98a00", "#c0362c"];
const METRO = "#6a4c93";
const STEP_ICONS = { start: "●", straight: "↑", left: "↰", right: "↱", metro: "▮", station: "◇" };
const PRESETS = [
  ["Dhanmondi", 23.7465, 90.376], ["Gulshan", 23.7925, 90.4078], ["Uttara", 23.8759, 90.3795],
  ["Motijheel", 23.733, 90.4172], ["Mirpur", 23.8223, 90.3654], ["Banani", 23.7937, 90.404],
];
const DHAKA_BOUNDS = [[23.69, 90.33], [23.9, 90.5]];
const AUTO_REFRESH_MS = 120000;
const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;

const state = {
  from: null, to: null, profile: "car", objective: "fastest", algorithm: "alt",
  blocks: [], hour: null, blocking: false, route: null, selected: 0,
  showTraffic: true, googleTraffic: false, googleMutant: null,
};
let meta = null, requestId = 0;

// ---- helpers -----------------------------------------------------------
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  node.append(...children);
  return node;
}
const api = async (path, body) => {
  const options = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
};
function toast(text) {
  const box = $("toast");
  box.textContent = text;
  box.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => box.classList.remove("show"), 4200);
}
const fmtTime = (s) => {
  const m = Math.round(s / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
};
const fmtKm = (m) => (m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`);
const fmtHour = (h) => `${h % 12 || 12} ${h < 12 ? "AM" : "PM"}`;
const inDhaka = (p) => p[0] >= 23.69 && p[0] <= 23.9 && p[1] >= 90.33 && p[1] <= 90.5;

// Keeps fitted content clear of the side panel, or the bottom sheet on phones.
function fitPadding() {
  return innerWidth > 720
    ? { paddingTopLeft: [20, 20], paddingBottomRight: [20, 20] }
    : { paddingTopLeft: [10, 10], paddingBottomRight: [10, Math.round(innerHeight * .6)] };
}

// ---- map ---------------------------------------------------------------
const map = L.map("map", { zoomControl: false, maxBounds: [[22.8, 89.7], [24.8, 91.2]], minZoom: 10 }).setView([23.795, 90.415], 12);
// A page opened in a hidden pane has no size yet, and fitBounds fails without one.
if (map.getSize().x > 0) map.fitBounds(DHAKA_BOUNDS, fitPadding());
L.control.zoom({ position: "topright" }).addTo(map);
const cartoLayer = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19, className: "basemap", attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);
const trafficRenderer = L.canvas({ padding: .3 });
const routeRenderer = L.canvas({ padding: .3 });
const trafficLayer = L.layerGroup().addTo(map);
const altLayer = L.layerGroup().addTo(map);
const routeLayer = L.layerGroup().addTo(map);
const stationLayer = L.layerGroup();
const blockLayer = L.layerGroup().addTo(map);
const markers = {};

// Paints the search frontier: thousands of points would be too slow as Leaflet markers.
const Frontier = L.Layer.extend({
  onAdd(m) {
    this.canvas = L.DomUtil.create("canvas", "leaflet-zoom-hide");
    m.getPanes().overlayPane.appendChild(this.canvas);
    m.on("moveend zoomend resize", this.reset, this);
    this.points = []; this.shown = 0;
    this.reset();
  },
  onRemove(m) { this.canvas.remove(); m.off("moveend zoomend resize", this.reset, this); },
  reset() {
    const size = this._map.getSize();
    L.DomUtil.setPosition(this.canvas, this._map.containerPointToLayerPoint([0, 0]));
    this.canvas.width = size.x; this.canvas.height = size.y;
    this.draw(1);
  },
  draw(alpha) {
    const ctx = this.canvas.getContext("2d");
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    ctx.globalAlpha = alpha * .6; ctx.fillStyle = "#22262b";
    for (let i = 0; i < this.shown; i++) {
      const p = this._map.latLngToContainerPoint(this.points[i]);
      ctx.fillRect(p.x - 1, p.y - 1, 2, 2);
    }
  },
  play(points, done) {
    cancelAnimationFrame(this.frame);
    this.points = points;
    if (calm || !points.length) { this.points = []; this.shown = 0; this.draw(1); done(); return; }
    const started = performance.now(), grow = 1100, fade = 450;
    const tick = (now) => {
      const t = now - started;
      this.shown = Math.min(points.length, Math.ceil(points.length * t / grow));
      if (t < grow) { this.draw(1); this.frame = requestAnimationFrame(tick); return; }
      if (!tick.finished) { tick.finished = true; done(); }
      const a = 1 - (t - grow) / fade;
      if (a > 0) { this.draw(a); this.frame = requestAnimationFrame(tick); } else { this.points = []; this.shown = 0; this.draw(1); }
    };
    this.frame = requestAnimationFrame(tick);
  },
  stop() { cancelAnimationFrame(this.frame); this.points = []; this.shown = 0; this.draw(1); },
});
const frontier = new Frontier().addTo(map);

function loadGoogle(key) {
  window.gm_authFailure = () => {
    if (state.googleMutant) map.removeLayer(state.googleMutant);
    cartoLayer.addTo(map);
    state.googleTraffic = false;
    toast("Google rejected the browser key, so the free map is showing instead.");
    refreshTraffic();
  };
  const fail = () => toast("Could not load Google Maps. Using the free map.");
  const google = el("script", { src: `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}`, async: "" });
  google.onerror = fail;
  const mutant = el("script", { src: "https://unpkg.com/leaflet.gridlayer.googlemutant@0.14.1/dist/Leaflet.GoogleMutant.js" });
  mutant.onerror = fail;
  mutant.onload = () => {
    state.googleMutant = L.gridLayer.googleMutant({
      type: "roadmap", maxZoom: 20,
      styles: [
        { elementType: "geometry", stylers: [{ color: "#141a21" }] },
        { elementType: "labels.text.fill", stylers: [{ color: "#9aa8b6" }] },
        { elementType: "labels.text.stroke", stylers: [{ color: "#0b0f14" }] },
        { featureType: "road", elementType: "geometry", stylers: [{ color: "#2a3542" }] },
        { featureType: "water", elementType: "geometry", stylers: [{ color: "#0a2230" }] },
        { featureType: "poi", stylers: [{ visibility: "off" }] },
      ],
    }).addTo(map);
    map.removeLayer(cartoLayer);
    state.googleTraffic = true;
    refreshTraffic();
  };
  document.head.append(google, mutant);
}

function setPin(which, point) {
  if (markers[which]) { markers[which].setLatLng(point); return; }
  const icon = L.divIcon({ className: "", html: `<div class="pin ${which === "from" ? "a" : "b"}"></div>`, iconSize: [22, 22], iconAnchor: [3, 26] });
  markers[which] = L.marker(point, { icon, draggable: true, keyboard: true, title: which === "from" ? "Start" : "Destination" }).addTo(map);
  markers[which].on("dragend", (e) => {
    const p = e.target.getLatLng();
    choose(which, [p.lat, p.lng], "Dropped pin");
  });
}

function choose(which, point, label) {
  if (!inDhaka(point)) { toast("That spot is outside the mapped Dhaka area."); return; }
  state[which] = point;
  $(which + "Input").value = label;
  $(which + "Suggest").replaceChildren();
  setPin(which, point);
  solve();
}

map.on("click", (e) => {
  const point = [e.latlng.lat, e.latlng.lng];
  const label = `${point[0].toFixed(4)}, ${point[1].toFixed(4)}`;
  if (state.blocking) {
    if (!inDhaka(point)) return;
    state.blocks.push(point);
    drawBlocks();
    solve();
  } else if (!state.from) choose("from", point, label);
  else choose("to", point, label);
});

function drawBlocks() {
  blockLayer.clearLayers();
  state.blocks.forEach((point, index) => {
    const icon = L.divIcon({ className: "", html: '<div class="blockmark">×</div>', iconSize: [22, 22] });
    L.marker(point, { icon, title: "Remove this closure" }).on("click", () => {
      state.blocks.splice(index, 1); drawBlocks(); solve();
    }).addTo(blockLayer);
  });
  $("closures").hidden = !state.blocks.length;
  $("closureText").textContent = `${state.blocks.length} road closure${state.blocks.length > 1 ? "s" : ""} applied`;
}

// ---- search box --------------------------------------------------------
function wireSearch(which) {
  const input = $(which + "Input"), list = $(which + "Suggest");
  let timer, token = 0;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) { list.replaceChildren(); return; }
    timer = setTimeout(async () => {
      const mine = ++token;
      try {
        const { results } = await api(`/api/search?q=${encodeURIComponent(q)}`);
        if (mine !== token) return;
        list.replaceChildren(...results.map((r) => el("button", {
          onclick: () => choose(which, [r.lat, r.lon], r.name),
        }, r.name, el("small", {}, r.detail))));
      } catch (error) { toast(error.message); }
    }, 320);
  });
  input.addEventListener("blur", () => setTimeout(() => list.replaceChildren(), 180));
}

// ---- solving -----------------------------------------------------------
function request() {
  const body = { from: state.from, to: state.to, profile: state.profile, objective: state.objective, blocks: state.blocks, hour: state.hour, algorithm: state.algorithm };
  if (state.objective === "custom") {
    body.weights = { distance: +$("wDistance").value, time: +$("wTime").value, cost: +$("wCost").value };
  }
  return body;
}

async function solve({ animate = true, fit = true } = {}) {
  if (!state.from || !state.to) {
    if (!state.from && !state.to) showHint();
    return;
  }
  const mine = ++requestId;
  if (animate) $("results").replaceChildren(el("div", { class: "hint loading" }, "Searching Dhaka’s roads…"));
  try {
    const route = await api("/api/route", request());
    if (mine !== requestId) return;
    state.route = route; state.selected = 0;
    altLayer.clearLayers(); routeLayer.clearLayers();
    const finish = () => { drawRoute(fit); renderResults(); };
    if (animate) {
      if (fit) map.fitBounds(L.latLngBounds([state.from, state.to]).pad(.25), fitPadding());
      frontier.play(route.visited.map(([a, b]) => L.latLng(a, b)), finish);
    } else finish();
  } catch (error) {
    if (mine !== requestId) return;
    frontier.stop(); state.route = null; altLayer.clearLayers(); routeLayer.clearLayers();
    $("results").replaceChildren(el("div", { class: "hint" }, error.message));
  }
}

function selectedRoute() {
  const r = state.route;
  return state.selected === 0 ? r : r.alternatives[state.selected - 1];
}

function drawRoute(fit) {
  routeLayer.clearLayers(); altLayer.clearLayers();
  const all = [state.route, ...state.route.alternatives];
  all.forEach((route, index) => {
    if (index === state.selected) return;
    route.segments.forEach((s) => L.polyline(s.points, { renderer: routeRenderer, color: "#8b929b", weight: 4, opacity: .8 })
      .on("click", (e) => { L.DomEvent.stop(e); pick(index); }).addTo(altLayer));
  });
  const route = selectedRoute();
  route.segments.forEach((s) => L.polyline(s.points, { renderer: routeRenderer, color: "#ffffff", weight: 8, opacity: 1, interactive: false }).addTo(routeLayer));
  route.segments.forEach((s) => {
    const color = s.kind === "metro" ? METRO : state.profile === "car" ? COLORS[s.level] : COLORS[0];
    const style = { renderer: routeRenderer, color, weight: 5, interactive: false, lineCap: "round" };
    if (s.kind !== "metro" && state.profile !== "car") style.dashArray = "1 9";
    L.polyline(s.points, style).addTo(routeLayer);
  });
  const ends = route.segments.flatMap((s) => s.points);
  if (fit && ends.length) map.fitBounds(L.latLngBounds(ends).pad(.08), fitPadding());
}

function pick(index) {
  state.selected = index;
  drawRoute(false);
  renderResults();
}

function showHint() {
  $("results").replaceChildren(el("div", { class: "hint" }, "Search for a place, tap a neighbourhood, or click the map twice to set your trip."));
}

function trafficNote(route) {
  if (route.traffic_source === "google") return "Using live Google traffic near sampled corridors.";
  if (route.traffic_source === "estimate") return "Traffic is estimated from the time of day. It is not a live reading.";
  return "";
}

function renderResults() {
  const route = selectedRoute(), main = state.route;
  const delay = route.seconds - route.free_seconds;
  const big = el("div", { class: "bigtime" }, fmtTime(route.seconds));
  if (delay > 60) big.append(el("small", {}, `+${fmtTime(delay)} traffic`));
  const stats = el("div", { class: "stats" },
    el("span", {}, el("b", {}, fmtKm(route.meters))),
    el("span", {}, el("b", {}, route.cost > 0 ? `৳${Math.round(route.cost)}` : "Free"), route.cost > 0 ? " est." : ""));
  const perf = el("div", { class: "perf" }, `${main.algorithm_label}: `, el("b", {}, `${main.settled.toLocaleString()}`),
    ` of ${main.graph_nodes.toLocaleString()} intersections explored in `, el("b", {}, `${main.ms} ms`));
  const summary = el("div", { class: "summary" }, big, stats, perf);
  const note = trafficNote(main);
  if (note) summary.append(el("div", { class: "note" }, note));

  const body = [summary];
  if (main.alternatives.length) {
    const options = [main, ...main.alternatives].map((r, i) => el("button", {
      class: `alt${i === state.selected ? " on" : ""}`, onclick: () => pick(i),
    }, el("span", {}, i ? `Alternative ${i}` : "Best route"), el("b", {}, `${fmtTime(r.seconds)} · ${fmtKm(r.meters)}`)));
    body.push(el("div", { class: "alts" }, ...options));
  }
  if (meta.google && state.profile !== "transit") {
    const card = el("div", { class: "googleCard" });
    const button = el("button", { class: "ghost wide", style: "margin:0", onclick: () => compareGoogle(card) }, "Compare with Google’s ETA");
    card.append(button);
    body.push(card);
  }
  body.push(el("div", { class: "sub" }, "Directions"));
  body.push(el("ol", { class: "steps" }, ...route.steps.map((step) => el("li", {
    class: step.icon, onclick: () => map.setView(step.at, 16),
  }, el("i", {}, STEP_ICONS[step.icon] || "•"), el("span", {}, step.text), el("small", {}, fmtKm(step.meters))))));
  $("results").replaceChildren(...body);
}

async function compareGoogle(card) {
  card.textContent = "Asking Google…";
  try {
    const g = await api("/api/google", request());
    const ours = selectedRoute();
    card.textContent = `Google: ${fmtTime(g.seconds)} over ${fmtKm(g.meters)} · This route: ${fmtTime(ours.seconds)} over ${fmtKm(ours.meters)}`;
    L.polyline(g.points, { renderer: routeRenderer, color: "#4f8cff", weight: 4, dashArray: "8 8", interactive: false }).addTo(routeLayer);
  } catch (error) { card.textContent = error.message; }
}

// ---- algorithm lab -----------------------------------------------------
async function race() {
  if (!state.from || !state.to) { toast("Set a start and destination first."); return; }
  const button = $("raceBtn");
  button.disabled = true;
  try {
    const data = await api("/api/compare", request());
    renderRace(data);
  } catch (error) { toast(error.message); } finally { button.disabled = false; }
}

function renderRace(data) {
  const rows = data.algorithms;
  const fewest = Math.min(...rows.map((r) => r.settled));
  const most = Math.max(...rows.map((r) => r.settled));
  const points = rows.flatMap((r) => r.visited);
  const lats = points.map((p) => p[0]), lons = points.map((p) => p[1]);
  const box = { s: Math.min(...lats), n: Math.max(...lats), w: Math.min(...lons), e: Math.max(...lons) };
  const cards = rows.map((r) => {
    const canvas = el("canvas", { width: 320, height: 320 });
    return { r, canvas, node: el("div", { class: `racer${r.settled === fewest ? " win" : ""}` }, canvas,
      el("h3", {}, r.label), el("p", {}, `${r.settled.toLocaleString()} explored · ${r.ms} ms`)) };
  });
  const verdict = data.agree
    ? `All four found the same optimal cost. Least exploration: ${rows.find((r) => r.settled === fewest).label}.`
    : "The algorithms disagreed. That should never happen, so treat this result as a bug.";
  $("race").replaceChildren(el("div", { class: "racers" }, ...cards.map((c) => c.node)), el("div", { class: `verdict${data.agree ? "" : " bad"}` }, verdict));
  animateRace(cards, box, most);
}

function animateRace(cards, box, most) {
  const span = Math.max(box.n - box.s, (box.e - box.w) * .916, 1e-4) * 1.08;
  const midLat = (box.n + box.s) / 2, midLon = (box.e + box.w) / 2;
  const toXY = (p, w) => [w / 2 + (p[1] - midLon) * .916 / span * w, w / 2 - (p[0] - midLat) / span * w];
  const total = calm ? 1 : 2600, started = performance.now();
  const tick = (now) => {
    let running = false;
    for (const { r, canvas } of cards) {
      const duration = total * r.settled / most;
      const shown = Math.ceil(r.visited.length * Math.min(1, (now - started) / duration));
      if (shown < r.visited.length) running = true;
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, 320, 320);
      ctx.fillStyle = "#1f5fbf";
      for (let i = 0; i < shown; i++) {
        const [x, y] = toXY(r.visited[i], 320);
        ctx.fillRect(x, y, 1.6, 1.6);
      }
    }
    if (running) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

// ---- traffic -----------------------------------------------------------
const trafficColor = (f) => COLORS[f >= 3 ? 2 : f >= 1.6 ? 1 : 0];
let trafficToken = 0;

async function refreshTraffic() {
  const mine = ++trafficToken;
  const q = state.hour === null ? "" : `?hour=${state.hour}`;
  let data;
  try { data = await api(`/api/traffic${q}`); } catch (error) { toast(error.message); return; }
  if (mine !== trafficToken) return;
  trafficLayer.clearLayers();
  if (state.googleMutant) {
    state.googleMutant.removeGoogleLayer?.("TrafficLayer");
    if (state.showTraffic && state.hour === null) state.googleMutant.addGoogleLayer("TrafficLayer");
  }
  const googleVisible = state.googleTraffic && state.hour === null;
  if (state.showTraffic && !googleVisible) {
    // Clear roads stay undrawn so the map only calls attention to congestion.
    data.roads.filter((road) => road.f >= 1.6).forEach((road) => L.polyline(road.p, { renderer: trafficRenderer, color: trafficColor(road.f), weight: 2, opacity: road.f >= 3 ? .65 : .5, interactive: false }).addTo(trafficLayer));
  }
  renderSource(data.source, googleVisible);
}

function renderSource(source, googleVisible) {
  const live = googleVisible || source === "google";
  $("liveBadge").textContent = live ? "Live" : "Estimate";
  $("liveBadge").classList.toggle("live", live);
  let title, text;
  if (state.hour !== null) { title = `Planned for ${fmtHour(state.hour)}`; text = "Future departures use the estimated daily traffic pattern."; }
  else if (source === "google") { title = "Live traffic is shaping routes"; text = "Route times use Google traffic on sampled corridors and estimates elsewhere."; }
  else if (googleVisible) { title = "Live traffic is on the map"; text = "Sync below to feed Google’s current traffic into the route search."; }
  else { title = "Estimated traffic"; text = "Colours come from a model of time of day and road type, not live sensors."; }
  $("sourceCard").replaceChildren(el("b", {}, title), text);
}

async function syncTraffic() {
  const button = $("syncBtn");
  button.disabled = true;
  try {
    const out = await api("/api/traffic/sync", {});
    toast(`Live traffic applied to ${out.edges.toLocaleString()} road segments.`);
    await refreshTraffic();
    solve({ animate: false, fit: false });
  } catch (error) { toast(error.message); } finally { button.disabled = false; }
}

function setHour(hour) {
  state.hour = hour;
  $("hourLabel").textContent = hour === null ? "Now" : fmtHour(hour);
  if (hour === null) $("hour").value = meta.dhaka_hour;
  refreshTraffic();
  solve({ animate: false, fit: false });
}

// ---- controls ----------------------------------------------------------
function wireSegment(id, key, after) {
  $(id).addEventListener("click", (e) => {
    const button = e.target.closest("button");
    if (!button) return;
    [...$(id).children].forEach((b) => b.classList.toggle("on", b === button));
    state[key] = button.dataset.v;
    after?.();
    solve({ fit: false });
  });
}

function init() {
  wireSearch("from"); wireSearch("to");
  $("presets").append(...PRESETS.map(([name, lat, lon]) => el("button", {
    onclick: () => choose(state.from ? "to" : "from", [lat, lon], name),
  }, name)));
  wireSegment("profile", "profile", () => {
    map[state.profile === "transit" ? "addLayer" : "removeLayer"](stationLayer);
  });
  wireSegment("objective", "objective", () => { $("customBox").hidden = state.objective !== "custom"; });
  for (const id of ["wDistance", "wTime", "wCost"]) {
    const slider = $(id), output = slider.nextElementSibling;
    output.textContent = slider.value;
    slider.addEventListener("input", () => { output.textContent = slider.value; });
    slider.addEventListener("change", () => solve({ fit: false }));
  }
  $("algorithm").append(...meta.algorithms.map((a) => el("option", { value: a.id }, a.label)));
  $("algorithm").addEventListener("change", (e) => { state.algorithm = e.target.value; solve({ fit: false }); });
  $("swap").addEventListener("click", () => {
    const [f, t, fl, tl] = [state.from, state.to, $("fromInput").value, $("toInput").value];
    state.from = t; state.to = f; $("fromInput").value = tl; $("toInput").value = fl;
    if (state.from) setPin("from", state.from); else { markers.from?.remove(); delete markers.from; }
    if (state.to) setPin("to", state.to); else { markers.to?.remove(); delete markers.to; }
    solve();
  });
  $("locate").addEventListener("click", () => {
    if (!navigator.geolocation) { toast("This browser cannot share location."); return; }
    navigator.geolocation.getCurrentPosition(
      (p) => choose("from", [p.coords.latitude, p.coords.longitude], "My location"),
      () => toast("Location permission was not available."), { enableHighAccuracy: true, timeout: 10000 });
  });
  $("blockBtn").addEventListener("click", () => {
    state.blocking = !state.blocking;
    $("blockBtn").setAttribute("aria-pressed", state.blocking);
    $("blockBtn").textContent = state.blocking ? "Done closing" : "Close a road";
    $("map").classList.toggle("picking", state.blocking);
    if (state.blocking) toast("Click any road on the map to close it.");
  });
  $("clearBlocks").addEventListener("click", () => { state.blocks = []; drawBlocks(); solve({ fit: false }); });
  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    document.querySelectorAll(".view").forEach((v) => { v.hidden = v.id !== `view-${tab.dataset.tab}`; });
  }));
  $("raceBtn").addEventListener("click", race);
  $("hour").value = meta.dhaka_hour;
  $("hour").addEventListener("input", (e) => { $("hourLabel").textContent = fmtHour(+e.target.value); });
  $("hour").addEventListener("change", (e) => setHour(+e.target.value));
  $("nowBtn").addEventListener("click", () => setHour(null));
  $("showTraffic").addEventListener("change", (e) => { state.showTraffic = e.target.checked; refreshTraffic(); });
  $("syncBtn").hidden = !meta.google;
  $("syncBtn").addEventListener("click", syncTraffic);
  meta.stations.forEach((s) => L.circleMarker([s.lat, s.lon], { radius: 5, color: "#fff", weight: 1.5, fillColor: METRO, fillOpacity: 1 })
    .bindTooltip(s.name).addTo(stationLayer));
  setInterval(() => {
    if (state.hour !== null) return;
    refreshTraffic();
    if (state.route) solve({ animate: false, fit: false });
  }, AUTO_REFRESH_MS);
}

(async function start() {
  try { meta = await api("/api/meta"); } catch {
    $("graphStat").textContent = "Server is not responding";
    showHint(); return;
  }
  const car = meta.stats.car;
  $("graphStat").textContent = `${car.nodes.toLocaleString()} intersections · ${car.edges.toLocaleString()} road segments`;
  init();
  showHint();
  await refreshTraffic();
  if (meta.browser_key) loadGoogle(meta.browser_key);
})();
