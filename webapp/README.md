# Dhaka Router

A web version of the CSE 373 routing project. It finds routes on Dhaka's real road
network instead of the original 6-node sample map.

## Run

Requires Python 3.10+ and NumPy.

    python server.py

Then open http://localhost:8373.

If `data/landmarks.npz` is missing, run `python build_graph.py` first. It downloads
current OpenStreetMap data and rebuilds both data files. To check the algorithms, run
`python test_routing.py`. To regenerate [BENCHMARK.md](BENCHMARK.md), run `python benchmark.py`.

## Adding Google Maps (optional)

Without a key the app uses OpenStreetMap tiles, Photon search and *estimated* traffic.
With a key you get Google's basemap, live traffic, Google place search and ETA checks.

1. In Google Cloud, create a project and enable billing.
2. Enable **Maps JavaScript API**, **Routes API** and **Places API (New)**.
3. Copy `.env.example` to `.env`, add the key and restart the server.

Google bills per request, so set a budget alert. "Sync live Google traffic" makes 8
Routes requests and is limited to once every 10 minutes.

## How routing works

Google does not expose its road graph, so the algorithms run on an OpenStreetMap graph:
47,692 intersections and 115,610 directed road segments for cars.

| Algorithm | Idea |
| --- | --- |
| Dijkstra | The original project's algorithm, kept as the baseline |
| Bidirectional Dijkstra | Searches from both ends and stops when the frontiers prove the best meeting point |
| A* | Uses straight-line distance at top speed as a lower bound |
| ALT | A* with a tighter bound from 12 precomputed landmarks and the triangle inequality |

ALT's landmark tables hold free-flow costs. Traffic and closures only make roads costlier,
so the bound stays valid without re-preprocessing, and answers stay exact. The bound does
get looser as congestion grows: [BENCHMARK.md](BENCHMARK.md) shows ALT is best on empty
roads, while bidirectional Dijkstra explores less at peak hours.

The original objectives remain: shortest, fastest, cheapest and the custom
`a*km + b*minutes + c*BDT` blend. Avoid-node became "Close a road" on the map. Alternative
routes use the penalty method.

## What is estimated

- Free-flow road speeds are assumptions per road type.
- Without a synced Google sample, traffic is a time-of-day and road-type model.
- Google samples only cover roads near 8 corridors. Other roads keep the estimate.
- Car cost (18 BDT/km) and metro fares are approximations.
- Buses from the original project are not included because OSM's Dhaka bus route data is incomplete.
- Kamalapur station is excluded because that extension is not in service.

## Files

    build_graph.py   OSM download, intersection graph, metro layer, landmarks
    engine.py        Graph and the four algorithms
    traffic.py       Congestion model and live traffic overlay
    google_api.py    Google Routes/Places and Photon clients
    server.py        JSON API and static file server
    static/          Map interface
    test_routing.py  Exactness and API tests on the real graph

Map data © OpenStreetMap contributors, available under the ODbL.
