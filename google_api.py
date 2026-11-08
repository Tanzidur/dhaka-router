"""Small server-side clients for Google Routes/Places, plus the keyless Photon search."""
import json
import os
import pathlib
import urllib.parse
import urllib.request

ROUTES = "https://routes.googleapis.com/directions/v2:computeRoutes"
PLACES = "https://places.googleapis.com/v1/places:searchText"
PHOTON = "https://photon.komoot.io/api/"
USER_AGENT = "CSE373-Dhaka-Router/1.0"
RECT = {"low": {"latitude": 23.69, "longitude": 90.33},
        "high": {"latitude": 23.90, "longitude": 90.50}}


def load_env():
    path = pathlib.Path(__file__).parent / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"'))


def browser_key():
    return os.environ.get("GOOGLE_MAPS_BROWSER_KEY") or os.environ.get("GOOGLE_MAPS_API_KEY") or ""


def server_key():
    return os.environ.get("GOOGLE_MAPS_SERVER_KEY") or os.environ.get("GOOGLE_MAPS_API_KEY") or ""


def _post(url, body, field_mask):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "X-Goog-Api-Key": server_key(),
        "X-Goog-FieldMask": field_mask})
    with urllib.request.urlopen(req, timeout=12) as response:
        return json.load(response)


def decode_polyline(text):
    points, i, lat, lon = [], 0, 0, 0
    while i < len(text):
        for axis in (0, 1):
            shift, value = 0, 0
            while True:
                b = ord(text[i]) - 63
                i += 1
                value |= (b & 0x1f) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(value >> 1) if value & 1 else value >> 1
            if axis == 0:
                lat += delta
            else:
                lon += delta
        points.append((lat / 1e5, lon / 1e5))
    return points


def _waypoint(point):
    return {"location": {"latLng": {"latitude": point[0], "longitude": point[1]}}}


def route(origin, destination, mode="DRIVE"):
    """Google's own route. Duration includes live traffic when mode is DRIVE."""
    body = {"origin": _waypoint(origin), "destination": _waypoint(destination), "travelMode": mode}
    if mode == "DRIVE":
        body["routingPreference"] = "TRAFFIC_AWARE"
    data = _post(ROUTES, body, "routes.duration,routes.staticDuration,routes.distanceMeters,routes.polyline.encodedPolyline")
    if not data.get("routes"):
        return None
    r = data["routes"][0]
    seconds = float(r["duration"].rstrip("s"))
    static = float(r.get("staticDuration", r["duration"]).rstrip("s"))
    return {"seconds": seconds, "static_seconds": static, "meters": r.get("distanceMeters", 0),
            "points": decode_polyline(r["polyline"]["encodedPolyline"])}


def sync_corridors(model, corridors, fetch=route):
    """Sample corridors, then spread each one's traffic ratio along its polyline."""
    lats, lons, ratios, errors = [], [], [], 0
    for origin, destination in corridors:
        try:
            result = fetch(origin, destination)
        except Exception:
            errors += 1
            continue
        if not result or result["static_seconds"] <= 0:
            errors += 1
            continue
        ratio = result["seconds"] / result["static_seconds"]
        for lat, lon in result["points"][::4]:
            lats.append(lat)
            lons.append(lon)
            ratios.append(ratio)
    if not lats:
        raise RuntimeError("Google returned no usable traffic for any corridor")
    return {"edges": model.apply_samples(lats, lons, ratios),
            "corridors": len(corridors) - errors, "failed": errors}


def search(query):
    if server_key():
        try:
            return _search_google(query)
        except Exception:
            pass  # A bad or quota-limited key should not take search down.
    return _search_photon(query)


def _search_google(query):
    data = _post(PLACES, {"textQuery": query, "maxResultCount": 6,
                          "locationRestriction": {"rectangle": RECT}},
                 "places.displayName,places.formattedAddress,places.location")
    return [{"name": p["displayName"]["text"], "detail": p.get("formattedAddress", ""),
             "lat": p["location"]["latitude"], "lon": p["location"]["longitude"]}
            for p in data.get("places", [])]


def _search_photon(query):
    params = urllib.parse.urlencode({"q": query, "limit": 6, "bbox": "90.33,23.69,90.50,23.90", "lang": "en"})
    req = urllib.request.Request(f"{PHOTON}?{params}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=8) as response:
        data = json.load(response)
    results = []
    for feature in data.get("features", []):
        p = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"]
        parts = [p.get("street"), p.get("district"), p.get("city")]
        name = p.get("name") or p.get("street") or "Unnamed place"
        results.append({"name": name, "detail": ", ".join(x for x in parts if x and x != name), "lat": lat, "lon": lon})
    return results
