#include "algorithms.h"

#include <chrono>
#include <limits>
#include <queue>
#include <utility>
#include <vector>

WeightFn makeWeightFn(RouteMode mode, const WeightConfig& cfg) {
    switch (mode) {
        case RouteMode::SHORTEST_DISTANCE:
            return [](const Edge& e) { return e.distance; };
        case RouteMode::FASTEST:
            return [](const Edge& e) { return e.time; };
        case RouteMode::CHEAPEST:
            return [](const Edge& e) { return e.cost; };
        case RouteMode::CUSTOM:
            return [cfg](const Edge& e) {
                return cfg.alpha * e.distance
                     + cfg.beta  * e.time
                     + cfg.gamma * e.cost;
            };
    }
    return [](const Edge& e) { return e.distance; };
}

// Dijkstra: O((V + E) log V) with a binary heap.
// Uses lazy deletion (stale entries are skipped on pop) instead of decrease-key.
RouteResult dijkstra(const Graph& g,
                     int source, int destination,
                     const WeightFn& weightOf,
                     const Constraints& constraints) {
    RouteResult result;

    const auto t0 = std::chrono::high_resolution_clock::now();
    auto finish = [&result, &t0]() -> RouteResult {
        const auto t1 = std::chrono::high_resolution_clock::now();
        result.executionMicros =
            std::chrono::duration_cast<std::chrono::microseconds>(t1 - t0).count();
        return result;
    };

    if (!g.hasNode(source) || !g.hasNode(destination)) return finish();
    if (constraints.avoidNodes.count(destination))     return finish();

    if (source == destination) {
        result.found = true;
        result.path.push_back(source);
        return finish();
    }

    const int    N   = g.nodeCount();
    const double INF = std::numeric_limits<double>::infinity();

    std::vector<double> dist(N, INF);
    std::vector<int>    prev(N, -1);
    std::vector<Edge>   prevEdge(N);  // edge used to reach node v under current best

    using QEntry = std::pair<double, int>;
    std::priority_queue<QEntry, std::vector<QEntry>, std::greater<QEntry>> pq;

    dist[source] = 0.0;
    pq.emplace(0.0, source);

    int nodesPopped = 0;

    while (!pq.empty()) {
        const auto [d, u] = pq.top();
        pq.pop();

        if (d > dist[u]) continue;  // stale entry from lazy deletion
        ++nodesPopped;

        if (u == destination) break;  // first non-stale pop of dst is optimal

        for (const Edge& e : g.neighbors(u)) {
            if (constraints.avoidNodes.count(e.to))   continue;
            if (constraints.avoidModes.count(e.mode)) continue;

            const double alt = d + weightOf(e);
            if (alt < dist[e.to]) {
                dist[e.to]     = alt;
                prev[e.to]     = u;
                prevEdge[e.to] = e;
                pq.emplace(alt, e.to);
            }
        }
    }

    result.nodesPopped = nodesPopped;

    if (dist[destination] == INF) return finish();

    std::vector<int>           reverseNodes;
    std::vector<TransportMode> reverseModes;
    double totDist = 0.0, totTime = 0.0, totCost = 0.0;

    for (int v = destination; v != -1; v = prev[v]) {
        reverseNodes.push_back(v);
        if (prev[v] != -1) {
            const Edge& e = prevEdge[v];
            reverseModes.push_back(e.mode);
            totDist += e.distance;
            totTime += e.time;
            totCost += e.cost;
        }
    }

    result.found         = true;
    result.path.assign(reverseNodes.rbegin(),  reverseNodes.rend());
    result.modes.assign(reverseModes.rbegin(), reverseModes.rend());
    result.totalDistance = totDist;
    result.totalTime     = totTime;
    result.totalCost     = totCost;

    return finish();
}

RouteResult route(const Graph& g,
                  int source, int destination,
                  RouteMode mode,
                  const WeightConfig& cfg,
                  const Constraints& constraints) {
    return dijkstra(g, source, destination, makeWeightFn(mode, cfg), constraints);
}
