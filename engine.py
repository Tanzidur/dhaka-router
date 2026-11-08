"""Graph loading and the shortest-path algorithms.

Every algorithm receives the same per-query edge weight list, so traffic, road
closures and the objective all change the search without changing its code.
"""
import heapq
import math
import pathlib
import time

import numpy as np

DATA = pathlib.Path(__file__).parent / "data"
EARTH_M = 6371008.8
ACTIVE_LANDMARKS = 6


class Graph:
    def __init__(self, profile, z, landmarks):
        p = profile + "_"
        self.profile = profile
        self.lat, self.lon = z[p + "lat"], z[p + "lon"]
        self.tail, self.head = z[p + "tail"], z[p + "head"]
        self.length, self.seconds, self.cost = z[p + "length"], z[p + "seconds"], z[p + "cost"]
        self.road_class, self.name_id = z[p + "class"], z[p + "name"]
        self.shape_offset, self.shape = z[p + "shape_offset"], z[p + "shape"]
        self.names = z[p + "names"].tolist()
        self.n, self.m = len(self.lat), len(self.tail)
        self.tails, self.heads = self.tail.tolist(), self.head.tolist()
        self.forward = [[] for _ in range(self.n)]
        self.backward = [[] for _ in range(self.n)]
        for eid, (u, v) in enumerate(zip(self.tails, self.heads)):
            self.forward[u].append((v, eid))
            self.backward[v].append((u, eid))
        # Best-case rates. They keep the geometric A* heuristic admissible.
        self.max_mps = float((self.length / self.seconds).max())
        self.min_bdt_per_m = float((self.cost / self.length).min())
        self.landmarks = {k: landmarks[p + k] for k in ("landmarks", "d_from", "d_to", "t_from", "t_to")}
        self.shape_edge = np.repeat(np.arange(self.m), np.diff(self.shape_offset))
        self.kx = math.cos(math.radians(float(self.lat.mean())))
        self.m_per_deg = EARTH_M * math.pi / 180

    def nearest_node(self, lat, lon):
        d = (self.lat - lat) ** 2 + ((self.lon - lon) * self.kx) ** 2
        return int(np.argmin(d))

    def edges_near(self, lat, lon, radius_m=25.0):
        """Edges around a point: includes both directions of a two-way road."""
        d = np.hypot(self.shape[:, 0] - lat, (self.shape[:, 1] - lon) * self.kx) * self.m_per_deg
        nearest = float(d.min())
        return np.unique(self.shape_edge[d <= max(radius_m, nearest + 1.0)])

    def geometry(self, eid):
        return self.shape[self.shape_offset[eid]:self.shape_offset[eid + 1]]

    def weights(self, alpha, beta, gamma, factor=None, blocked=None):
        """alpha/m + beta/s + gamma/BDT. Traffic multiplies time and is always >= 1."""
        seconds = self.seconds if factor is None else self.seconds * factor
        w = alpha * self.length + beta * seconds + gamma * self.cost
        if blocked is not None and len(blocked):
            w = w.copy()
            w[blocked] = np.inf
        return w.tolist()

    def geo_heuristic(self, t, alpha, beta, gamma):
        """Straight-line lower bound from every node to t."""
        p1, p2 = np.radians(self.lat), math.radians(float(self.lat[t]))
        dphi = p2 - p1
        dl = np.radians(float(self.lon[t]) - self.lon)
        a = np.sin(dphi / 2) ** 2 + np.cos(p1) * math.cos(p2) * np.sin(dl / 2) ** 2
        meters = 2 * EARTH_M * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
        rate = alpha + beta / self.max_mps + gamma * self.min_bdt_per_m
        return (meters * rate * (1 - 1e-9)).tolist()

    def alt_heuristic(self, s, t, alpha, beta, gamma):
        """Triangle-inequality bound using the landmarks most useful for s -> t."""
        L = self.landmarks

        def bound(frm, to):
            return np.maximum(frm[:, [t]] - frm, to - to[:, [t]])

        scores = bound(L["d_from"], L["d_to"])[:, s]
        active = np.argsort(scores)[-ACTIVE_LANDMARKS:]
        meters = np.maximum(bound(L["d_from"][active], L["d_to"][active]).max(axis=0), 0)
        seconds = np.maximum(bound(L["t_from"][active], L["t_to"][active]).max(axis=0), 0)
        h = alpha * meters + beta * seconds + gamma * self.min_bdt_per_m * meters
        return (h * (1 - 1e-9)).tolist()


def load_graphs():
    with np.load(DATA / "dhaka_graph.npz") as raw, np.load(DATA / "landmarks.npz") as marks:
        z, landmarks = dict(raw), dict(marks)
    return {p: Graph(p, z, landmarks) for p in ("car", "walk", "transit")}, z


def _result(g, s, t, parent, cost, settled, visited, started):
    elapsed = (time.perf_counter() - started) * 1000
    if not math.isfinite(cost):
        return {"found": False, "settled": settled, "ms": elapsed, "visited": visited, "edges": [], "cost": None}
    edges = []
    v = t
    while v != s:
        eid = parent[v]
        edges.append(eid)
        v = g.tails[eid]
    edges.reverse()
    return {"found": True, "settled": settled, "ms": elapsed, "visited": visited, "edges": edges, "cost": cost}


def dijkstra(g, s, t, w):
    started = time.perf_counter()
    dist, parent = [math.inf] * g.n, [-1] * g.n
    dist[s] = 0.0
    heap, visited = [(0.0, s)], []
    pop, push, adj = heapq.heappop, heapq.heappush, g.forward
    while heap:
        d, u = pop(heap)
        if d > dist[u]:
            continue
        visited.append(u)
        if u == t:
            break
        for v, eid in adj[u]:
            nd = d + w[eid]
            if nd < dist[v]:
                dist[v], parent[v] = nd, eid
                push(heap, (nd, v))
    return _result(g, s, t, parent, dist[t], len(visited), visited, started)


def _guided(g, s, t, w, h, started):
    """A* with re-opening, so it stays exact even if a bound is only just consistent."""
    dist, parent = [math.inf] * g.n, [-1] * g.n
    dist[s] = 0.0
    heap, visited = [(h[s], 0.0, s)], []
    pop, push, adj = heapq.heappop, heapq.heappush, g.forward
    while heap:
        _, d, u = pop(heap)
        if d > dist[u]:
            continue
        visited.append(u)
        if u == t:
            break
        for v, eid in adj[u]:
            nd = d + w[eid]
            if nd < dist[v]:
                dist[v], parent[v] = nd, eid
                push(heap, (nd + h[v], nd, v))
    return _result(g, s, t, parent, dist[t], len(visited), visited, started)


def astar(g, s, t, w, coef):
    started = time.perf_counter()
    return _guided(g, s, t, w, g.geo_heuristic(t, *coef), started)


def alt(g, s, t, w, coef):
    started = time.perf_counter()
    return _guided(g, s, t, w, g.alt_heuristic(s, t, *coef), started)


def bidirectional(g, s, t, w):
    """Grow from both ends; stop once the two frontiers cannot improve the best meeting."""
    started = time.perf_counter()
    if s == t:
        return _result(g, s, t, [-1] * g.n, 0.0, 0, [], started)
    pop, push = heapq.heappop, heapq.heappush
    dist = ([math.inf] * g.n, [math.inf] * g.n)
    parent = ([-1] * g.n, [-1] * g.n)
    done = (bytearray(g.n), bytearray(g.n))
    heaps = ([(0.0, s)], [(0.0, t)])
    dist[0][s] = dist[1][t] = 0.0
    adjacency = (g.forward, g.backward)
    best, meet, visited = math.inf, -1, []
    while heaps[0] and heaps[1]:
        if heaps[0][0][0] + heaps[1][0][0] >= best:
            break
        side = 0 if heaps[0][0][0] <= heaps[1][0][0] else 1
        d, u = pop(heaps[side])
        if done[side][u] or d > dist[side][u]:
            continue
        done[side][u] = 1
        visited.append(u)
        mine, other = dist[side], dist[1 - side]
        for v, eid in adjacency[side][u]:
            nd = d + w[eid]
            if nd < mine[v]:
                mine[v], parent[side][v] = nd, eid
                push(heaps[side], (nd, v))
            if nd + other[v] < best and math.isfinite(nd):
                best, meet = nd + other[v], v
    if meet == -1:
        return _result(g, s, t, parent[0], math.inf, len(visited), visited, started)
    elapsed = (time.perf_counter() - started) * 1000
    edges = []
    v = meet
    while v != s:
        eid = parent[0][v]
        edges.append(eid)
        v = g.tails[eid]
    edges.reverse()
    v = meet
    while v != t:
        eid = parent[1][v]
        edges.append(eid)
        v = g.heads[eid]
    return {"found": True, "settled": len(visited), "ms": elapsed, "visited": visited, "edges": edges, "cost": best}


ALGORITHMS = {
    "alt": ("ALT (A* + Landmarks)", True),
    "astar": ("A* (straight-line)", True),
    "bidirectional": ("Bidirectional Dijkstra", False),
    "dijkstra": ("Dijkstra (CSE 373 original)", False),
}


def run(name, g, s, t, w, coef):
    if name == "dijkstra":
        return dijkstra(g, s, t, w)
    if name == "bidirectional":
        return bidirectional(g, s, t, w)
    if name == "astar":
        return astar(g, s, t, w, coef)
    if name == "alt":
        return alt(g, s, t, w, coef)
    raise ValueError(f"unknown algorithm {name!r}")
