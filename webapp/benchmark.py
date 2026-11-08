"""Compare the routing algorithms over many random Dhaka car trips.

    python benchmark.py            # 300 trips per condition
    python benchmark.py --trips 50 # quicker run

Writes BENCHMARK.md (summary) and benchmark_results.csv (one row per run).
"""
import argparse
import csv
import datetime as dt
import math
import pathlib
import platform
import random
import sys

import numpy as np

import engine
import server

HERE = pathlib.Path(__file__).parent
SEED = 373
MONDAY = 0  # a working day in Dhaka, so results do not depend on when this runs
CONDITIONS = [("2 AM, near-empty roads", 2), ("9 AM, morning peak", 9),
              ("1 PM, midday", 13), ("6 PM, evening peak", 18)]
BANDS = [("Under 5 km", 0, 5), ("5 to 15 km", 5, 15), ("Over 15 km", 15, math.inf)]


def run_all(app, trips):
    g = app.graphs["car"]
    coef = server.OBJECTIVES["fastest"]
    rng = random.Random(SEED)
    pairs = []
    while len(pairs) < trips:
        s, t = rng.randrange(g.n), rng.randrange(g.n)
        if s != t:
            pairs.append((s, t))
    rows, disagreements = [], 0
    for label, hour in CONDITIONS:
        print(f"{label}...", flush=True)
        weights = g.weights(*coef, app.traffic.factors(hour, MONDAY))
        for trip, (s, t) in enumerate(pairs):
            results = {name: engine.run(name, g, s, t, weights, coef) for name in engine.ALGORITHMS}
            costs = [r["cost"] for r in results.values()]
            exact = max(costs) - min(costs) <= 1e-6 * max(1.0, max(costs))
            disagreements += not exact
            km = float(g.length[results["dijkstra"]["edges"]].sum()) / 1000
            for name, r in results.items():
                rows.append({"condition": label, "hour": hour, "trip": trip, "algorithm": name,
                             "km": round(km, 3), "settled": r["settled"], "ms": round(r["ms"], 3),
                             "route_minutes": round(r["cost"] / 60, 3), "exact": exact})
    return rows, disagreements


def select(rows, **match):
    return [r for r in rows if all(r[k] == v for k, v in match.items())]


def wins(rows, condition):
    """Share of trips where each algorithm settled the fewest nodes (ties share credit)."""
    trips, score = {}, dict.fromkeys(engine.ALGORITHMS, 0.0)
    for r in select(rows, condition=condition):
        trips.setdefault(r["trip"], []).append(r)
    for group in trips.values():
        fewest = min(r["settled"] for r in group)
        winners = [r["algorithm"] for r in group if r["settled"] == fewest]
        for name in winners:
            score[name] += 1 / len(winners)
    return {name: 100 * value / len(trips) for name, value in score.items()}


def condition_table(rows, condition):
    base = np.mean([r["settled"] for r in select(rows, condition=condition, algorithm="dijkstra")])
    share = wins(rows, condition)
    lines = ["| Algorithm | Mean explored | Median explored | vs Dijkstra | Mean ms | 95th pct ms | Explored least |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name, (label, _) in engine.ALGORITHMS.items():
        picked = select(rows, condition=condition, algorithm=name)
        settled = np.array([r["settled"] for r in picked])
        ms = np.array([r["ms"] for r in picked])
        lines.append(f"| {label} | {settled.mean():,.0f} | {np.median(settled):,.0f} | {settled.mean() / base:.0%} "
                     f"| {ms.mean():.1f} | {np.percentile(ms, 95):.1f} | {share[name]:.0f}% |")
    return lines


def band_table(rows, condition):
    lines = ["| Trip length | Trips | " + " | ".join(v[0] for v in engine.ALGORITHMS.values()) + " |",
             "| --- | ---: | " + " | ".join("---:" for _ in engine.ALGORITHMS) + " |"]
    scoped = select(rows, condition=condition)
    for label, low, high in BANDS:
        inside = [r for r in scoped if low <= r["km"] < high]
        count = len(select(inside, algorithm="dijkstra"))
        if not count:
            continue
        cells = [f"{np.mean([r['settled'] for r in select(inside, algorithm=name)]):,.0f}" for name in engine.ALGORITHMS]
        lines.append(f"| {label} | {count} | " + " | ".join(cells) + " |")
    return lines


def report(rows, disagreements, trips, g):
    lines = [
        "# Routing benchmark", "",
        f"Generated {dt.date.today().isoformat()} on Python {platform.python_version()}. "
        f"Each condition runs the same {trips} random car trips (seed {SEED}), optimizing for fastest "
        f"time on a working-day traffic model. Graph: {g.n:,} intersections, {g.m:,} directed road segments.", "",
        f"**Exactness:** {disagreements} of {trips * len(CONDITIONS)} trips had algorithms disagree on the optimal cost.", "",
        "\"Explored\" counts intersections settled by the search, which does not depend on machine speed. "
        "Times are from a single run in pure Python, and A* and ALT include computing their heuristic for "
        "every node, so treat explored counts as the main measure.", "",
    ]
    for label, _ in CONDITIONS:
        lines += [f"## {label}", ""] + condition_table(rows, label) + [""]
    for label, _ in (CONDITIONS[0], CONDITIONS[3]):
        lines += [f"## Mean intersections explored by trip length: {label}", ""] + band_table(rows, label) + [""]
    lines += ["Raw per-run data is in `benchmark_results.csv`.", ""]
    return "\n".join(lines)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--trips", type=int, default=300)
    args = parser.parse_args()
    app = server.App()
    rows, disagreements = run_all(app, args.trips)
    with open(HERE / "benchmark_results.csv", "w", newline="", encoding="utf8") as out:
        writer = csv.DictWriter(out, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (HERE / "BENCHMARK.md").write_text(report(rows, disagreements, args.trips, app.graphs["car"]), encoding="utf8")
    print(f"Done. Disagreements: {disagreements}. Wrote BENCHMARK.md and benchmark_results.csv")


if __name__ == "__main__":
    main()
