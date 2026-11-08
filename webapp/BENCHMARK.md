# Routing benchmark

Generated 2026-11-09 on Python 3.14.8. Each condition runs the same 300 random car trips (seed 373), optimizing for fastest time on a working-day traffic model. Graph: 47,692 intersections, 115,610 directed road segments.

**Exactness:** 0 of 1200 trips had algorithms disagree on the optimal cost.

"Explored" counts intersections settled by the search, which does not depend on machine speed. Times are from a single run in pure Python, and A* and ALT include computing their heuristic for every node, so treat explored counts as the main measure.

## 2 AM, near-empty roads

| Algorithm | Mean explored | Median explored | vs Dijkstra | Mean ms | 95th pct ms | Explored least |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ALT (A* + Landmarks) | 4,688 | 3,097 | 19% | 14.5 | 27.9 | 97% |
| A* (straight-line) | 12,770 | 10,717 | 51% | 17.2 | 41.3 | 0% |
| Bidirectional Dijkstra | 12,655 | 12,059 | 51% | 19.1 | 42.5 | 3% |
| Dijkstra (CSE 373 original) | 24,877 | 25,367 | 100% | 27.1 | 49.9 | 0% |

## 9 AM, morning peak

| Algorithm | Mean explored | Median explored | vs Dijkstra | Mean ms | 95th pct ms | Explored least |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ALT (A* + Landmarks) | 15,658 | 14,635 | 64% | 28.3 | 54.4 | 23% |
| A* (straight-line) | 19,451 | 18,739 | 79% | 25.3 | 53.6 | 0% |
| Bidirectional Dijkstra | 12,887 | 13,212 | 52% | 19.4 | 39.0 | 77% |
| Dijkstra (CSE 373 original) | 24,597 | 24,764 | 100% | 26.9 | 50.3 | 0% |

## 1 PM, midday

| Algorithm | Mean explored | Median explored | vs Dijkstra | Mean ms | 95th pct ms | Explored least |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ALT (A* + Landmarks) | 13,870 | 12,416 | 56% | 26.2 | 50.1 | 41% |
| A* (straight-line) | 18,377 | 17,240 | 74% | 24.1 | 52.3 | 0% |
| Bidirectional Dijkstra | 12,793 | 12,909 | 52% | 19.6 | 40.1 | 59% |
| Dijkstra (CSE 373 original) | 24,678 | 25,252 | 100% | 27.4 | 51.3 | 0% |

## 6 PM, evening peak

| Algorithm | Mean explored | Median explored | vs Dijkstra | Mean ms | 95th pct ms | Explored least |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ALT (A* + Landmarks) | 16,161 | 15,154 | 66% | 29.3 | 56.4 | 21% |
| A* (straight-line) | 19,753 | 19,198 | 80% | 26.3 | 56.9 | 0% |
| Bidirectional Dijkstra | 12,922 | 13,112 | 53% | 19.8 | 40.1 | 79% |
| Dijkstra (CSE 373 original) | 24,577 | 24,604 | 100% | 27.2 | 51.9 | 0% |

## Mean intersections explored by trip length: 2 AM, near-empty roads

| Trip length | Trips | ALT (A* + Landmarks) | A* (straight-line) | Bidirectional Dijkstra | Dijkstra (CSE 373 original) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Under 5 km | 28 | 531 | 1,293 | 1,175 | 3,313 |
| 5 to 15 km | 158 | 3,267 | 8,972 | 8,779 | 19,939 |
| Over 15 km | 114 | 7,679 | 20,854 | 20,847 | 37,017 |

## Mean intersections explored by trip length: 6 PM, evening peak

| Trip length | Trips | ALT (A* + Landmarks) | A* (straight-line) | Bidirectional Dijkstra | Dijkstra (CSE 373 original) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Under 5 km | 30 | 1,872 | 2,482 | 1,493 | 3,401 |
| 5 to 15 km | 148 | 12,513 | 15,486 | 10,179 | 19,946 |
| Over 15 km | 122 | 24,100 | 29,175 | 19,059 | 35,403 |

Raw per-run data is in `benchmark_results.csv`.
