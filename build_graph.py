"""Turn OpenStreetMap data for Dhaka into routable graphs.

    python build_graph.py                 # download from Overpass, then build
    python build_graph.py --raw raw.json  # build from an earlier download

Writes data/dhaka_graph.npz (road graphs) and data/landmarks.npz (ALT tables).
"""
import argparse
import heapq
import json
import math
import pathlib
import random
import sys
import time
import urllib.parse
import urllib.request

import numpy as np

HERE = pathlib.Path(__file__).parent
DATA = HERE / "data"
BBOX = (23.69, 90.33, 23.90, 90.50)  # south, west, north, east

OVERPASS = "https://overpass-api.de/api/interpreter"
QUERY = """[out:json][timeout:170];
(way["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link|service|footway|path|pedestrian|steps)$"]({b});
node["station"="subway"]({b}););
out body;>;out skel qt;""".replace("{b}", ",".join(map(str, BBOX)))

# Road classes, shared with the traffic model. Speeds are free-flow km/h
# assumptions for Dhaka, because few OSM roads here carry a maxspeed tag.
CLASSES = {
    "motorway": 60, "motorway_link": 40, "trunk": 50, "trunk_link": 35,
    "primary": 40, "primary_link": 30, "secondary": 32, "secondary_link": 26,
    "tertiary": 26, "tertiary_link": 22, "unclassified": 22, "residential": 18,
    "living_street": 14, "service": 12, "footway": 5, "path": 5,
    "pedestrian": 5, "steps": 3, "metro": 0, "transfer": 0,
}
CLASS_NAMES = list(CLASSES)
CLASS_ID = {name: i for i, name in enumerate(CLASS_NAMES)}
CAR_ONLY_EXCLUDED = {"footway", "path", "pedestrian", "steps"}

WALK_KMH = 4.8
CAR_BDT_PER_KM = 18.0      # rough fuel + running cost
METRO_KMH = 33.0           # average, including station dwell
METRO_BDT_PER_KM = 5.0     # approximates the published distance-based fare
METRO_BOARD_BDT = 15.0     # with the per-km rate, gives about the 20 BDT minimum
METRO_BOARD_SECONDS = 300  # walk to the platform plus the average wait
METRO_ALIGHT_SECONDS = 90

# Operating order of MRT Line 6. Kamalapur exists in OSM but is left out
# because that extension is not in service.
MRT6 = ["Uttara North", "Uttara Center", "Uttara South", "Pallabi", "Mirpur 11",
        "Mirpur 10", "Kazipara", "Shewrapara", "Agargaon", "Bijoy Sarawni",
        "Farmgate", "Karwan Bazar", "Shahbagh", "Dhaka University",
        "Bangladesh Secretariat", "Motijheel"]
LANDMARK_COUNT = 12


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2 +
         math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 6371008.8 * math.asin(math.sqrt(a))


def download():
    body = urllib.parse.urlencode({"data": QUERY}).encode()
    req = urllib.request.Request(OVERPASS, data=body,
                                 headers={"User-Agent": "CSE373-Dhaka-Router/1.0"})
    print("Downloading Dhaka from Overpass (about 2 minutes)...")
    with urllib.request.urlopen(req, timeout=280) as r:
        return json.load(r)


def usable(tags, profile):
    kind = tags.get("highway")
    if kind not in CLASSES or tags.get("area") == "yes":
        return False
    if tags.get("access") in ("no", "private"):
        return False
    if profile == "car":
        if kind in CAR_ONLY_EXCLUDED or tags.get("service") in ("parking_aisle", "driveway"):
            return False
        return tags.get("motor_vehicle") not in ("no", "private") and tags.get("motorcar") != "no"
    return kind != "motorway" and tags.get("foot") not in ("no", "private")


def direction(tags, profile):
    """Return (forward allowed, backward allowed)."""
    if profile == "walk":
        return True, True
    oneway = tags.get("oneway")
    if oneway in ("yes", "1", "true") or tags.get("junction") == "roundabout" or tags.get("highway") == "motorway":
        return oneway != "-1", False
    if oneway == "-1":
        return False, True
    return True, True


def build_profile(ways, coords, profile):
    """Cut ways at intersections so that graph nodes are only decision points."""
    selected = [w for w in ways if usable(w.get("tags", {}), profile)]
    seen = {}
    for way in selected:
        for ref in way["nodes"]:
            seen[ref] = seen.get(ref, 0) + 1
    ids, edges = {}, []
    names = {"": 0}

    def node_id(ref):
        return ids.setdefault(ref, len(ids))

    for way in selected:
        tags = way["tags"]
        refs = [r for r in way["nodes"] if r in coords]
        if len(refs) < 2:
            continue
        forward, backward = direction(tags, profile)
        kind = tags["highway"]
        speed = WALK_KMH if profile == "walk" else CLASSES[kind]
        name = tags.get("name:en") or tags.get("name") or ""
        name_id = names.setdefault(name, len(names))
        start = 0
        for i in range(1, len(refs)):
            if i < len(refs) - 1 and seen[refs[i]] < 2:
                continue
            piece = refs[start:i + 1]
            start = i
            if piece[0] == piece[-1] and len(piece) < 3:
                continue
            points = [coords[r] for r in piece]
            length = sum(haversine(*a, *b) for a, b in zip(points, points[1:]))
            if length <= 0:
                continue
            u, v = node_id(piece[0]), node_id(piece[-1])
            record = (length, length / (speed / 3.6), CLASS_ID[kind], name_id)
            if forward:
                edges.append((u, v, *record, points))
            if backward:
                edges.append((v, u, *record, points[::-1]))
    latlon = [None] * len(ids)
    for ref, i in ids.items():
        latlon[i] = coords[ref]
    return latlon, edges, list(names)


def largest_scc(n, edges):
    """Iterative Kosaraju; keeps routing free of unreachable fragments."""
    out, back = [[] for _ in range(n)], [[] for _ in range(n)]
    for e in edges:
        out[e[0]].append(e[1])
        back[e[1]].append(e[0])
    seen, order = [False] * n, []
    for root in range(n):
        if seen[root]:
            continue
        seen[root] = True
        stack = [(root, 0)]
        while stack:
            u, i = stack.pop()
            if i < len(out[u]):
                stack.append((u, i + 1))
                v = out[u][i]
                if not seen[v]:
                    seen[v] = True
                    stack.append((v, 0))
            else:
                order.append(u)
    comp, count = [-1] * n, 0
    for root in reversed(order):
        if comp[root] != -1:
            continue
        comp[root] = count
        stack = [root]
        while stack:
            u = stack.pop()
            for v in back[u]:
                if comp[v] == -1:
                    comp[v] = count
                    stack.append(v)
        count += 1
    sizes = [0] * count
    for c in comp:
        sizes[c] += 1
    best = max(range(count), key=sizes.__getitem__)
    return [c == best for c in comp]


def keep_component(latlon, edges):
    keep = largest_scc(len(latlon), edges)
    remap, kept = {}, []
    for i, ok in enumerate(keep):
        if ok:
            remap[i] = len(kept)
            kept.append(latlon[i])
    return kept, [(remap[e[0]], remap[e[1]], *e[2:]) for e in edges if keep[e[0]] and keep[e[1]]]


def add_metro(latlon, edges, stations):
    """Layer MRT Line 6 on the walking graph."""
    by_name = {s["tags"].get("name:en"): s for s in stations}
    missing = [n for n in MRT6 if n not in by_name]
    if missing:
        sys.exit(f"Stations missing from OSM data: {missing}")
    lat = np.array([p[0] for p in latlon])
    lon = np.array([p[1] for p in latlon])
    k = math.cos(math.radians(23.8))
    platform = []
    for name in MRT6:
        s = by_name[name]
        nearest = int(np.argmin((lat - s["lat"]) ** 2 + ((lon - s["lon"]) * k) ** 2))
        pid = len(latlon)
        latlon.append((s["lat"], s["lon"]))
        platform.append(pid)
        link = max(haversine(s["lat"], s["lon"], *latlon[nearest]), 1.0)
        here = (s["lat"], s["lon"])
        shape = [latlon[nearest], here]
        walk = link / (WALK_KMH / 3.6)
        edges.append((nearest, pid, link, walk + METRO_BOARD_SECONDS, CLASS_ID["transfer"], 0, shape))
        edges.append((pid, nearest, link, walk + METRO_ALIGHT_SECONDS, CLASS_ID["transfer"], 0, shape[::-1]))
    for a, b in zip(range(len(MRT6)), range(1, len(MRT6))):
        u, v = platform[a], platform[b]
        length = haversine(*latlon[u], *latlon[v])
        seconds = length / (METRO_KMH / 3.6)
        shape = [latlon[u], latlon[v]]
        edges.append((u, v, length, seconds, CLASS_ID["metro"], 0, shape))
        edges.append((v, u, length, seconds, CLASS_ID["metro"], 0, shape[::-1]))
    return platform


def costs(profile, edges):
    out = np.zeros(len(edges))
    for i, e in enumerate(edges):
        if profile == "car":
            out[i] = e[2] / 1000 * CAR_BDT_PER_KM
        elif e[4] == CLASS_ID["metro"]:
            out[i] = e[2] / 1000 * METRO_BDT_PER_KM
        elif e[4] == CLASS_ID["transfer"] and e[3] > METRO_BOARD_SECONDS:
            out[i] = METRO_BOARD_BDT
    return out


def sssp(n, adj, weight, source):
    dist = [math.inf] * n
    dist[source] = 0.0
    heap = [(0.0, source)]
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist[u]:
            continue
        for v, eid in adj[u]:
            nd = d + weight[eid]
            if nd < dist[v]:
                dist[v] = nd
                heapq.heappush(heap, (nd, v))
    return dist


def build_landmarks(n, tails, heads, length, seconds):
    """Farthest-point landmark selection, then distance tables both ways."""
    forward, backward = [[] for _ in range(n)], [[] for _ in range(n)]
    for eid, (u, v) in enumerate(zip(tails.tolist(), heads.tolist())):
        forward[u].append((v, eid))
        backward[v].append((u, eid))
    lengths, times = length.tolist(), seconds.tolist()
    chosen = [random.Random(373).randrange(n)]
    best = np.array(sssp(n, forward, lengths, chosen[0]))
    chosen = [int(np.argmax(best))]  # replace the random seed with a peripheral node
    best = np.array(sssp(n, forward, lengths, chosen[0]))
    while len(chosen) < LANDMARK_COUNT:
        chosen.append(int(np.argmax(best)))
        best = np.minimum(best, np.array(sssp(n, forward, lengths, chosen[-1])))
    tables = {"landmarks": np.array(chosen)}
    for key, adj, weight in (("d_from", forward, lengths), ("d_to", backward, lengths),
                             ("t_from", forward, times), ("t_to", backward, times)):
        tables[key] = np.array([sssp(n, adj, weight, l) for l in chosen])
    return tables


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", help="existing Overpass JSON")
    args = parser.parse_args()
    raw = json.load(open(args.raw, encoding="utf8")) if args.raw else download()
    DATA.mkdir(exist_ok=True)
    coords = {e["id"]: (e["lat"], e["lon"]) for e in raw["elements"] if e["type"] == "node"}
    ways = [e for e in raw["elements"] if e["type"] == "way"]
    stations = [e for e in raw["elements"]
                if e["type"] == "node" and e.get("tags", {}).get("station") == "subway"]

    arrays = {"class_names": np.array(CLASS_NAMES)}
    landmark_arrays = {}
    station_nodes = None
    base_walk = None
    for profile in ("car", "walk", "transit"):
        started = time.time()
        if profile == "transit":
            latlon, edges, names = base_walk
            latlon, edges = list(latlon), list(edges)
            station_nodes = add_metro(latlon, edges, stations)
        else:
            latlon, edges, names = build_profile(ways, coords, profile)
            latlon, edges = keep_component(latlon, edges)
            if profile == "walk":
                base_walk = (latlon, edges, names)
        tails = np.array([e[0] for e in edges], dtype=np.int32)
        heads = np.array([e[1] for e in edges], dtype=np.int32)
        length = np.array([e[2] for e in edges])
        seconds = np.array([e[3] for e in edges])
        offsets = np.cumsum([0] + [len(e[6]) for e in edges], dtype=np.int64)
        shape = np.array([p for e in edges for p in e[6]])
        p = profile + "_"
        arrays.update({
            p + "lat": np.array([x[0] for x in latlon]), p + "lon": np.array([x[1] for x in latlon]),
            p + "tail": tails, p + "head": heads, p + "length": length, p + "seconds": seconds,
            p + "cost": costs(profile, edges), p + "class": np.array([e[4] for e in edges], dtype=np.int16),
            p + "name": np.array([e[5] for e in edges], dtype=np.int32),
            p + "shape_offset": offsets, p + "shape": shape, p + "names": np.array(names),
        })
        for key, table in build_landmarks(len(latlon), tails, heads, length, seconds).items():
            landmark_arrays[p + key] = table
        print(f"{profile}: {len(latlon):,} nodes, {len(edges):,} edges ({time.time() - started:.0f}s)")

    arrays["station_nodes"] = np.array(station_nodes)
    arrays["station_names"] = np.array(MRT6)
    np.savez_compressed(DATA / "dhaka_graph.npz", **arrays)
    np.savez(DATA / "landmarks.npz", **landmark_arrays)
    print("Saved to", DATA)


if __name__ == "__main__":
    main()
