#ifndef GRAPH_H
#define GRAPH_H

#include <cstddef>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

enum class TransportMode { BUS, METRO, WALK };

struct EnumClassHash {
    template <typename T>
    std::size_t operator()(T t) const noexcept {
        return static_cast<std::size_t>(t);
    }
};

std::string transportModeToString(TransportMode m);
bool        parseTransportMode(const std::string& s, TransportMode& out);

struct Edge {
    int           to;
    double        distance;  // km
    double        time;      // min
    double        cost;      // BDT
    TransportMode mode;
};

struct Node {
    int         id;
    std::string name;
};

enum class RouteMode { SHORTEST_DISTANCE, FASTEST, CHEAPEST, CUSTOM };

// Coefficients for the custom blended weight: alpha*dist + beta*time + gamma*cost
struct WeightConfig {
    double alpha = 1.0;
    double beta  = 0.0;
    double gamma = 0.0;
};

struct Constraints {
    std::unordered_set<int>                          avoidNodes;
    std::unordered_set<TransportMode, EnumClassHash> avoidModes;
};

struct RouteResult {
    bool                       found           = false;
    std::vector<int>           path;
    std::vector<TransportMode> modes;           // size = path.size() - 1
    double                     totalDistance   = 0.0;
    double                     totalTime       = 0.0;
    double                     totalCost       = 0.0;
    long long                  executionMicros = 0;
    int                        nodesPopped     = 0;
};

class Graph {
public:
    bool loadFromFile(const std::string& path);
    void addNode(int id, const std::string& name);
    void addEdge(int from, int to,
                 double distance, double time, double cost,
                 TransportMode mode,
                 bool bidirectional = true);

    const std::vector<Edge>& neighbors(int nodeId) const;
    int                      nodeCount() const;
    int                      edgeCount() const;
    std::string              nameOf(int nodeId) const;
    int                      idOf(const std::string& name) const;
    bool                     hasNode(int nodeId) const;

    void clear();

private:
    std::vector<std::vector<Edge>>       adj_;
    std::unordered_map<int, std::string> idToName_;
    std::unordered_map<std::string, int> nameToId_;
};

#endif
