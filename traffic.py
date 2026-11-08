"""Edge-level congestion factors.

Without Google data this is an estimate from time of day and road class. With a
Google key, sampled corridors replace the estimate near those corridors.
Factors are never below 1, so the free-flow landmark bounds stay admissible.
"""
import datetime as dt
import threading
import time

import numpy as np

DHAKA = dt.timezone(dt.timedelta(hours=6))

# Share of the day's worst congestion, for each hour in Dhaka.
HOUR_INTENSITY = np.array([.04, .03, .03, .03, .04, .08, .18, .42, .78, .9, .78, .66,
                           .62, .62, .66, .72, .86, 1.0, 1.0, .9, .7, .46, .24, .1])
SENSITIVITY = {
    "motorway": .3, "motorway_link": .6, "trunk": 2.0, "trunk_link": 1.8,
    "primary": 2.2, "primary_link": 1.9, "secondary": 1.8, "secondary_link": 1.5,
    "tertiary": 1.3, "tertiary_link": 1.1, "unclassified": .9, "residential": .6,
    "living_street": .4, "service": .3,
}
CENTER = (23.76, 90.40)
COVER_RADIUS_M = 1200.0
SYNC_COOLDOWN_S = 600

# Corridors sampled during a live sync: each one is one billable Routes request.
CORRIDORS = [
    ((23.8759, 90.3795), (23.7925, 90.4078)),  # Uttara to Gulshan
    ((23.7925, 90.4078), (23.7330, 90.4172)),  # Gulshan to Motijheel
    ((23.8223, 90.3654), (23.7580, 90.3890)),  # Mirpur to Farmgate
    ((23.7580, 90.3890), (23.7330, 90.4172)),  # Farmgate to Motijheel
    ((23.7465, 90.3760), (23.7937, 90.4040)),  # Dhanmondi to Banani
    ((23.7465, 90.3760), (23.7330, 90.4172)),  # Dhanmondi to Motijheel
    ((23.8223, 90.3654), (23.7925, 90.4078)),  # Mirpur to Gulshan
    ((23.8000, 90.4250), (23.7400, 90.4300)),  # Badda to Malibagh side
]


def dhaka_now():
    return dt.datetime.now(DHAKA)


def intensity(hour=None, weekday=None):
    now = dhaka_now()
    hour = now.hour if hour is None else hour
    weekday = now.weekday() if weekday is None else weekday
    weekend = {4: .45, 5: .7}.get(weekday, 1.0)  # Friday and Saturday
    return float(HOUR_INTENSITY[int(hour) % 24] * weekend)


class TrafficModel:
    def __init__(self, car_graph, class_names):
        self.g = car_graph
        sens = np.array([SENSITIVITY.get(name, 0.0) for name in class_names])
        self.sensitivity = sens[car_graph.road_class]
        mid_lat = (car_graph.lat[car_graph.tail] + car_graph.lat[car_graph.head]) / 2
        mid_lon = (car_graph.lon[car_graph.tail] + car_graph.lon[car_graph.head]) / 2
        self.mid_lat, self.mid_lon = mid_lat, mid_lon
        km = np.hypot(mid_lat - CENTER[0], (mid_lon - CENTER[1]) * car_graph.kx) * 111.2
        self.central = 1 + .6 * np.exp(-(km / 5.0) ** 2)
        self.live = None        # (factor overlay, coverage mask)
        self.live_at = 0.0
        self.live_samples = 0
        self.version = 0
        self.lock = threading.Lock()

    def factors(self, hour=None, weekday=None):
        """hour=None means now, which is the only case that uses live samples."""
        factor = 1 + intensity(hour, weekday) * self.sensitivity * self.central
        live = self.live
        if hour is None and live is not None and time.time() - self.live_at < 2 * SYNC_COOLDOWN_S:
            factor = np.where(live[1], live[0], factor)
        return factor

    def source(self, hour=None):
        if hour is None and self.live is not None and time.time() - self.live_at < 2 * SYNC_COOLDOWN_S:
            return "google"
        return "estimate"

    def apply_samples(self, lats, lons, ratios):
        """Blend Google's traffic ratios onto edges close to the sampled corridors."""
        lats, lons = np.asarray(lats), np.asarray(lons)
        ratios = np.maximum(np.asarray(ratios, dtype=float), 1.0)
        best, near = np.full(self.g.m, np.inf), np.zeros(self.g.m, dtype=np.int64)
        for i, (lat, lon) in enumerate(zip(lats, lons)):
            d = np.hypot(self.mid_lat - lat, (self.mid_lon - lon) * self.g.kx) * self.g.m_per_deg
            closer = d < best
            best[closer], near[closer] = d[closer], i
        # Sensitivity scaling keeps side streets near a jammed arterial calmer than it.
        arterial = self.sensitivity >= 1.3
        covered = (best <= COVER_RADIUS_M) & arterial
        overlay = np.maximum(ratios[near], 1.0)
        self.live, self.live_at = (overlay, covered), time.time()
        self.live_samples = int(covered.sum())
        self.version += 1
        return self.live_samples

    def can_sync(self):
        return time.time() - self.live_at >= SYNC_COOLDOWN_S

    def seconds_until_sync(self):
        return max(0, int(SYNC_COOLDOWN_S - (time.time() - self.live_at)))
