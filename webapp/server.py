"""Dhaka Router: API and static file server. Run with: python server.py"""
import json
import math
import mimetypes
import pathlib
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

import engine
import google_api
import traffic as traffic_mod

STATIC = pathlib.Path(__file__).parent / "static"
PORT = 8373
MAX_VISITED = 7000
MAX_SNAP_M = 1500
OBJECTIVES = {
    "fastest": (0, 1, 0), "shortest": (1, 0, 0),
    "cheapest": (0, 0.0005, 1),  # the tiny time term breaks ties on free routes
}
COLOR_LEVELS = (1.6, 3.0)


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class App:
    def __init__(self):
        google_api.load_env()
        started = time.time()
        self.graphs, raw = engine.load_graphs()
        self.classes = raw["class_names"].tolist()
        self.stations = {int(n): str(name) for n, name in zip(raw["station_nodes"], raw["station_names"])}
        self.traffic = traffic_mod.TrafficModel(self.graphs["car"], self.classes)
        print(f"Loaded graphs in {time.time() - started:.1f}s")

    # --- request parsing -------------------------------------------------
    def point(self, value, label):
        try:
            lat, lon = float(value[0]), float(value[1])
        except (TypeError, ValueError, IndexError):
            raise ApiError(f"{label} needs a latitude and longitude") from None
        if not (23.69 <= lat <= 23.90 and 90.33 <= lon <= 90.50):
            raise ApiError(f"{label} is outside the mapped Dhaka area")
        return lat, lon

    def coefficients(self, body):
        objective = body.get("objective", "fastest")
        if objective in OBJECTIVES:
            return OBJECTIVES[objective]
        if objective == "custom":
            w = body.get("weights") or {}
            try:
                # Same model as the CLI: a*km + b*minutes + c*BDT.
                a, b, c = (max(float(w.get(k, 0)), 0.0) for k in ("distance", "time", "cost"))
            except (TypeError, ValueError):
                raise ApiError("custom weights must be numbers") from None
            if a + b + c <= 0:
                raise ApiError("Set at least one custom weight above zero")
            return a / 1000, b / 60, c
        raise ApiError(f"unknown objective {objective!r}")

    def query(self, body):
        profile = body.get("profile", "car")
        if profile not in self.graphs:
            raise ApiError(f"unknown travel mode {profile!r}")
        g = self.graphs[profile]
        origin, target = self.point(body.get("from"), "Start"), self.point(body.get("to"), "Destination")
        s, t = g.nearest_node(*origin), g.nearest_node(*target)
        for label, p, node in (("Start", origin, s), ("Destination", target, t)):
            gap = float(np.hypot(g.lat[node] - p[0], (g.lon[node] - p[1]) * g.kx) * g.m_per_deg)
            if gap > MAX_SNAP_M:
                raise ApiError(f"{label} is {gap / 1000:.1f} km from the nearest usable road")
        coef = self.coefficients(body)
        hour = body.get("hour")
        if hour is not None:
            hour = int(hour)
            if not 0 <= hour <= 23:
                raise ApiError("hour must be between 0 and 23")
        factor = self.traffic.factors(hour) if profile == "car" else None
        blocked = None
        if body.get("blocks"):
            found = [g.edges_near(*self.point(b, "Road closure")) for b in body["blocks"][:50]]
            blocked = np.unique(np.concatenate(found))
        return g, s, t, coef, factor, blocked, hour

    # --- output ----------------------------------------------------------
    def describe(self, g, edges, factor):
        seconds = g.seconds[edges] * (1 if factor is None else factor[edges]) if edges else np.array([])
        return {
            "meters": float(g.length[edges].sum()) if edges else 0.0,
            "seconds": float(seconds.sum()) if edges else 0.0,
            "free_seconds": float(g.seconds[edges].sum()) if edges else 0.0,
            "cost": float(g.cost[edges].sum()) if edges else 0.0,
            "segments": self.segments(g, edges, factor),
            "steps": self.steps(g, edges),
        }

    def kind(self, g, eid):
        name = self.classes[int(g.road_class[eid])]
        return name if name in ("metro", "transfer") else "road"

    def segments(self, g, edges, factor):
        """Route pieces ready to draw, split where mode or congestion changes."""
        out = []
        for eid in edges:
            kind = self.kind(g, eid)
            value = 1.0 if factor is None else float(factor[eid])
            level = sum(value >= cut for cut in COLOR_LEVELS)
            points = np.round(g.geometry(eid), 6).tolist()
            if out and out[-1]["kind"] == kind and out[-1]["level"] == level:
                out[-1]["points"].extend(points[1:])
            else:
                out.append({"kind": kind, "level": level, "points": points})
        return out

    def bearing(self, a, b, kx):
        return math.degrees(math.atan2((b[1] - a[1]) * kx, b[0] - a[0])) % 360

    def steps(self, g, edges):
        groups = []
        for eid in edges:
            kind = self.kind(g, eid)
            name = g.names[int(g.name_id[eid])] if kind == "road" else ""
            if groups and groups[-1]["kind"] == kind and groups[-1]["name"] == name:
                groups[-1]["edges"].append(eid)
                groups[-1]["meters"] += float(g.length[eid])
            else:
                groups.append({"kind": kind, "name": name, "edges": [eid], "meters": float(g.length[eid])})
        out, previous = [], None
        for group in groups:
            first, last = group["edges"][0], group["edges"][-1]
            shape = g.geometry(first)
            start_bearing = self.bearing(shape[0], shape[min(1, len(shape) - 1)], g.kx)
            if group["kind"] == "metro":
                begin = self.stations.get(g.tails[first], "station")
                end = self.stations.get(g.heads[last], "station")
                text, icon = f"Ride MRT Line 6 from {begin} to {end} ({len(group['edges'])} stops)", "metro"
            elif group["kind"] == "transfer":
                station = self.stations.get(g.heads[last]) or self.stations.get(g.tails[first], "station")
                boarding = g.heads[last] in self.stations
                text, icon = (f"Enter {station} station" if boarding else f"Exit {station} station"), "station"
            else:
                road = group["name"] or "unnamed road"
                if previous is None:
                    text, icon = f"Head along {road}", "start"
                else:
                    turn = (start_bearing - previous + 180) % 360 - 180
                    if abs(turn) < 30:
                        text, icon = f"Continue onto {road}", "straight"
                    elif turn > 0:
                        text, icon = f"Turn {'slightly ' if turn < 60 else ''}right onto {road}", "right"
                    else:
                        text, icon = f"Turn {'slightly ' if turn > -60 else ''}left onto {road}", "left"
            end_shape = g.geometry(last)
            previous = self.bearing(end_shape[max(len(end_shape) - 2, 0)], end_shape[-1], g.kx)
            out.append({"text": text, "icon": icon, "meters": round(group["meters"]),
                        "at": np.round(shape[0], 6).tolist()})
        return out

    def visited(self, g, nodes):
        step = max(1, len(nodes) // MAX_VISITED)
        sample = np.asarray(nodes[::step], dtype=np.int64)
        return np.round(np.column_stack((g.lat[sample], g.lon[sample])), 5).tolist() if len(sample) else []

    # --- endpoints -------------------------------------------------------
    def alternatives(self, g, s, t, name, weights, coef, factor, best, wanted=2):
        """Penalty method: make used roads costlier, search again, keep what differs."""
        found, used = [], [set(best)]
        length = g.length.tolist()
        w = list(weights)
        for eid in best:
            w[eid] *= 1.4
        for _ in range(6):
            if len(found) == wanted:
                break
            result = engine.run(name, g, s, t, w, coef)
            if not result["found"]:
                break
            current = set(result["edges"])
            total = sum(length[e] for e in current) or 1
            overlap = max(sum(length[e] for e in current & other) / total for other in used)
            if overlap < 0.8:
                used.append(current)
                route = self.describe(g, result["edges"], factor)
                route["objective_cost"] = sum(weights[e] for e in result["edges"])
                found.append(route)
            for eid in current:
                w[eid] *= 1.4
        return found

    def route(self, body):
        g, s, t, coef, factor, blocked, hour = self.query(body)
        name = body.get("algorithm", "alt")
        if name not in engine.ALGORITHMS:
            raise ApiError(f"unknown algorithm {name!r}")
        weights = g.weights(*coef, factor, blocked)
        result = engine.run(name, g, s, t, weights, coef)
        if not result["found"]:
            raise ApiError("No route found. Road closures may have cut this trip off.", 404)
        response = self.describe(g, result["edges"], factor)
        response.update(
            algorithm=name, algorithm_label=engine.ALGORITHMS[name][0], settled=result["settled"],
            ms=round(result["ms"], 2), objective_cost=result["cost"], graph_nodes=g.n,
            visited=self.visited(g, result["visited"]),
            traffic_source=self.traffic.source(hour) if factor is not None else "none",
            snap=[[float(g.lat[s]), float(g.lon[s])], [float(g.lat[t]), float(g.lon[t])]],
        )
        response["alternatives"] = self.alternatives(g, s, t, name, weights, coef, factor, result["edges"])
        return response

    def compare(self, body):
        g, s, t, coef, factor, blocked, _ = self.query(body)
        weights = g.weights(*coef, factor, blocked)
        rows = []
        for name, (label, _) in engine.ALGORITHMS.items():
            runs = [engine.run(name, g, s, t, weights, coef) for _ in range(3)]
            best = min(runs, key=lambda r: r["ms"])
            rows.append({"id": name, "label": label, "found": best["found"], "settled": best["settled"],
                         "ms": round(best["ms"], 2), "cost": best["cost"],
                         "visited": self.visited(g, best["visited"])})
        costs = [r["cost"] for r in rows if r["cost"] is not None]
        agree = bool(costs) and len(costs) == len(rows) and max(costs) - min(costs) <= 1e-6 * max(1.0, max(costs))
        return {"algorithms": rows, "agree": agree, "graph_nodes": g.n}

    def google(self, body):
        if not google_api.server_key():
            raise ApiError("Add a Google key to .env to compare with Google", 409)
        origin, target = self.point(body.get("from"), "Start"), self.point(body.get("to"), "Destination")
        mode = {"car": "DRIVE", "walk": "WALK"}.get(body.get("profile", "car"))
        if mode is None:
            raise ApiError("Google comparison covers car and walking trips")
        result = self.google_call(google_api.route, origin, target, mode)
        if result is None:
            raise ApiError("Google found no route for this trip", 404)
        return result

    def google_call(self, function, *args):
        try:
            return function(*args)
        except Exception as error:
            raise ApiError(f"Google request failed: {error}", 502) from None

    def sync(self):
        if not google_api.server_key():
            raise ApiError("Add a Google key to .env to use live traffic", 409)
        if not self.traffic.can_sync():
            raise ApiError(f"Live traffic was just synced. Try again in {self.traffic.seconds_until_sync()} s.", 429)
        with self.traffic.lock:
            result = self.google_call(google_api.sync_corridors, self.traffic, traffic_mod.CORRIDORS)
        return result

    def overlay(self, hour):
        g, factor = self.graphs["car"], self.traffic.factors(hour)
        main = np.isin(g.road_class, [self.classes.index(c) for c in
                                      ("motorway", "trunk", "primary", "secondary", "tertiary")])
        keep = np.nonzero(main & (g.tail < g.head))[0]
        return {"source": self.traffic.source(hour), "roads": [
            {"f": round(float(factor[e]), 2), "p": np.round(g.geometry(e)[:: 2], 5).tolist() + [np.round(g.geometry(e)[-1], 5).tolist()]}
            for e in keep.tolist()]}

    def meta(self):
        return {
            "browser_key": google_api.browser_key(), "google": bool(google_api.server_key()),
            "algorithms": [{"id": k, "label": v[0]} for k, v in engine.ALGORITHMS.items()],
            "stats": {p: {"nodes": g.n, "edges": g.m} for p, g in self.graphs.items()},
            "stations": [{"name": n, "lat": float(self.graphs["transit"].lat[i]), "lon": float(self.graphs["transit"].lon[i])}
                         for i, n in self.stations.items()],
            "dhaka_hour": traffic_mod.dhaka_now().hour,
        }


class Handler(BaseHTTPRequestHandler):
    app = None

    def log_message(self, *args):
        pass

    def send_json(self, data, status=200):
        payload = json.dumps(data, separators=(",", ":"), allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def guarded(self, action):
        try:
            self.send_json(action())
        except ApiError as error:
            self.send_json({"error": str(error)}, error.status)
        except Exception as error:
            print("Server error:", repr(error), file=sys.stderr)
            self.send_json({"error": "The server hit an unexpected problem"}, 500)

    def do_POST(self):
        routes = {"/api/route": self.app.route, "/api/compare": self.app.compare, "/api/google": self.app.google}

        def action():
            size = int(self.headers.get("Content-Length") or 0)
            if size > 100_000:
                raise ApiError("Request too large", 413)
            try:
                body = json.loads(self.rfile.read(size) or b"{}")
            except json.JSONDecodeError:
                raise ApiError("Request body must be JSON") from None
            if self.path == "/api/traffic/sync":
                return self.app.sync()
            if self.path not in routes:
                raise ApiError("Not found", 404)
            return routes[self.path](body)

        self.guarded(action)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        params = urllib.parse.parse_qs(url.query)
        if url.path == "/api/meta":
            return self.guarded(self.app.meta)
        if url.path == "/api/search":
            def search():
                query = params.get("q", [""])[0].strip()
                try:
                    return {"results": google_api.search(query) if len(query) >= 2 else []}
                except Exception:
                    raise ApiError("Place search is unavailable right now", 502) from None
            return self.guarded(search)
        if url.path == "/api/traffic":
            hour = params.get("hour", [""])[0]
            return self.guarded(lambda: self.app.overlay(int(hour) % 24 if hour.isdigit() else None))
        self.serve_static(url.path)

    def serve_static(self, path):
        relative = "index.html" if path == "/" else urllib.parse.unquote(path).lstrip("/")
        target = (STATIC / relative).resolve()
        if not target.is_relative_to(STATIC.resolve()) or not target.is_file():
            self.send_error(404)
            return
        payload = target.read_bytes()
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", kind + ("; charset=utf-8" if kind.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(payload)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    Handler.app = App()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Dhaka Router running at http://localhost:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
