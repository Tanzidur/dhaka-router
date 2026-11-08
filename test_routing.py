"""Checks exactness on the real Dhaka graph. Run with: python test_routing.py"""
import random
import sys
import unittest

import numpy as np

import engine
import google_api
import server
import traffic as traffic_mod

APP = server.App()
FAST, SHORT, CHEAP = server.OBJECTIVES["fastest"], server.OBJECTIVES["shortest"], server.OBJECTIVES["cheapest"]
NAMES = list(engine.ALGORITHMS)


def assert_valid_path(case, g, s, t, result, w):
    edges = result["edges"]
    case.assertEqual(g.tails[edges[0]], s)
    case.assertEqual(g.heads[edges[-1]], t)
    for a, b in zip(edges, edges[1:]):
        case.assertEqual(g.heads[a], g.tails[b])
    case.assertAlmostEqual(sum(w[e] for e in edges), result["cost"], places=5)


class Exactness(unittest.TestCase):
    def check(self, profile, coef, factor=None, blocked=None, trials=25, seed=373):
        g, rng = APP.graphs[profile], random.Random(seed)
        w = g.weights(*coef, factor, blocked)
        for _ in range(trials):
            s, t = rng.randrange(g.n), rng.randrange(g.n)
            if s == t:
                continue
            base = engine.run("dijkstra", g, s, t, w, coef)
            for name in NAMES[:-1]:
                other = engine.run(name, g, s, t, w, coef)
                self.assertEqual(base["found"], other["found"], (name, s, t))
                if base["found"]:
                    self.assertLess(abs(base["cost"] - other["cost"]), 1e-6 * max(1, base["cost"]), (name, s, t))
                    assert_valid_path(self, g, s, t, other, w)

    def test_car_fastest(self):
        self.check("car", FAST)

    def test_car_shortest(self):
        self.check("car", SHORT)

    def test_car_cheapest(self):
        self.check("car", CHEAP)

    def test_rush_hour_traffic(self):
        self.check("car", FAST, APP.traffic.factors(18))

    def test_custom_blend(self):
        self.check("car", (0.5 / 1000, 1 / 60, 0.2), APP.traffic.factors(9))

    def test_road_closures(self):
        g, rng = APP.graphs["car"], random.Random(5)
        blocked = np.array(rng.sample(range(g.m), 3000))
        self.check("car", FAST, blocked=blocked)

    def test_walk(self):
        self.check("walk", FAST)

    def test_transit(self):
        self.check("transit", FAST)
        self.check("transit", CHEAP, trials=10)

    def test_heuristics_never_overestimate(self):
        g = APP.graphs["car"]
        coef = FAST
        w = g.weights(*coef)
        rng = random.Random(1)
        for _ in range(8):
            s, t = rng.randrange(g.n), rng.randrange(g.n)
            truth = engine.dijkstra(g, s, t, w)["cost"]
            self.assertLessEqual(g.geo_heuristic(t, *coef)[s], truth + 1e-6)
            self.assertLessEqual(g.alt_heuristic(s, t, *coef)[s], truth + 1e-6)

    def test_alt_explores_less_on_long_trips(self):
        g, w = APP.graphs["car"], APP.graphs["car"].weights(*FAST)
        s, t = g.nearest_node(23.8759, 90.3795), g.nearest_node(23.7330, 90.4172)
        dij = engine.dijkstra(g, s, t, w)["settled"]
        self.assertLess(engine.alt(g, s, t, w, FAST)["settled"], dij / 3)


class Api(unittest.TestCase):
    TRIP = {"from": [23.8759, 90.3795], "to": [23.7330, 90.4172]}

    def test_route_and_compare(self):
        result = APP.route({**self.TRIP, "profile": "car", "objective": "fastest", "hour": 18})
        self.assertGreater(result["meters"], 15000)
        self.assertGreater(result["seconds"], result["free_seconds"])
        self.assertTrue(result["steps"])
        self.assertTrue(APP.compare({**self.TRIP, "profile": "car", "objective": "fastest"})["agree"])

    def test_metro_is_used_when_it_helps(self):
        result = APP.route({**self.TRIP, "profile": "transit", "objective": "fastest"})
        self.assertIn("metro", {s["kind"] for s in result["segments"]})
        self.assertGreater(result["cost"], 0)

    def test_closure_changes_route(self):
        first = APP.route({**self.TRIP, "profile": "car", "objective": "fastest", "hour": 2})
        points = [p for s in first["segments"] for p in s["points"]]
        closed = points[len(points) // 2]
        second = APP.route({**self.TRIP, "profile": "car", "objective": "fastest", "hour": 2, "blocks": [closed]})
        self.assertGreaterEqual(second["seconds"], first["seconds"])
        self.assertNotEqual([s["points"] for s in first["segments"]], [s["points"] for s in second["segments"]])

    def test_rejects_bad_input(self):
        for bad in ({"from": [1, 2], "to": self.TRIP["to"]}, {**self.TRIP, "profile": "plane"},
                    {**self.TRIP, "objective": "custom", "weights": {}}, {"to": self.TRIP["to"]}):
            with self.assertRaises(server.ApiError):
                APP.route(bad)


class Live(unittest.TestCase):
    def test_polyline(self):
        self.assertEqual(google_api.decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@"),
                         [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)])

    def test_sync_overrides_estimate_near_corridor(self):
        model = traffic_mod.TrafficModel(APP.graphs["car"], APP.classes)
        line = [(23.76 + i * .002, 90.39) for i in range(30)]
        fake = lambda *_: {"seconds": 900, "static_seconds": 300, "meters": 1, "points": line}
        out = google_api.sync_corridors(model, [((0, 0), (0, 0))], fetch=fake)
        self.assertGreater(out["edges"], 0)
        self.assertEqual(model.source(), "google")
        self.assertEqual(model.source(9), "estimate")
        factor = model.factors()
        self.assertTrue(np.all(factor >= 1))
        self.assertAlmostEqual(float(factor[model.live[1]].max()), 3.0)
        self.assertFalse(model.can_sync())


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    unittest.main(verbosity=1)
