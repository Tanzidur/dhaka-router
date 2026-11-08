#ifndef ALGORITHMS_H
#define ALGORITHMS_H

#include "graph.h"
#include <functional>

using WeightFn = std::function<double(const Edge&)>;

WeightFn makeWeightFn(RouteMode mode, const WeightConfig& cfg);

// Single-source shortest path with binary-heap Dijkstra.
// Skips edges whose target is in avoidNodes or whose mode is in avoidModes.
RouteResult dijkstra(const Graph& g,
                     int source, int destination,
                     const WeightFn& weightOf,
                     const Constraints& constraints);

RouteResult route(const Graph& g,
                  int source, int destination,
                  RouteMode mode,
                  const WeightConfig& cfg,
                  const Constraints& constraints);

#endif
