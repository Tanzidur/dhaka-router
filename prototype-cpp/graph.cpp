#include "graph.h"

#include <fstream>
#include <iostream>
#include <sstream>

std::string transportModeToString(TransportMode m) {
    switch (m) {
        case TransportMode::BUS:   return "BUS";
        case TransportMode::METRO: return "METRO";
        case TransportMode::WALK:  return "WALK";
    }
    return "?";
}

bool parseTransportMode(const std::string& s, TransportMode& out) {
    if (s == "BUS")   { out = TransportMode::BUS;   return true; }
    if (s == "METRO") { out = TransportMode::METRO; return true; }
    if (s == "WALK")  { out = TransportMode::WALK;  return true; }
    return false;
}

void Graph::clear() {
    adj_.clear();
    idToName_.clear();
    nameToId_.clear();
}

void Graph::addNode(int id, const std::string& name) {
    if (id < 0) return;
    if (static_cast<std::size_t>(id) >= adj_.size()) {
        adj_.resize(static_cast<std::size_t>(id) + 1);
    }
    idToName_[id]   = name;
    nameToId_[name] = id;
}

void Graph::addEdge(int from, int to,
                    double distance, double time, double cost,
                    TransportMode mode, bool bidirectional) {
    if (!hasNode(from) || !hasNode(to)) return;
    adj_[from].push_back(Edge{to, distance, time, cost, mode});
    if (bidirectional && from != to) {
        adj_[to].push_back(Edge{from, distance, time, cost, mode});
    }
}

const std::vector<Edge>& Graph::neighbors(int nodeId) const {
    static const std::vector<Edge> EMPTY;
    if (!hasNode(nodeId)) return EMPTY;
    return adj_[static_cast<std::size_t>(nodeId)];
}

int Graph::nodeCount() const {
    return static_cast<int>(adj_.size());
}

int Graph::edgeCount() const {
    int total = 0;
    for (const auto& bucket : adj_) total += static_cast<int>(bucket.size());
    return total;
}

std::string Graph::nameOf(int nodeId) const {
    auto it = idToName_.find(nodeId);
    return (it == idToName_.end()) ? std::string() : it->second;
}

int Graph::idOf(const std::string& name) const {
    auto it = nameToId_.find(name);
    return (it == nameToId_.end()) ? -1 : it->second;
}

bool Graph::hasNode(int nodeId) const {
    return idToName_.find(nodeId) != idToName_.end();
}

namespace {

void stripComment(std::string& line) {
    auto hash = line.find('#');
    if (hash != std::string::npos) line.erase(hash);
}

void trim(std::string& s) {
    const char* WS = " \t\r\n";
    auto first = s.find_first_not_of(WS);
    if (first == std::string::npos) { s.clear(); return; }
    auto last = s.find_last_not_of(WS);
    s = s.substr(first, last - first + 1);
}

}  // namespace

bool Graph::loadFromFile(const std::string& path) {
    clear();

    std::ifstream in(path);
    if (!in) {
        std::cerr << "Error: cannot open '" << path << "'\n";
        return false;
    }

    enum class Section { NONE, NODES, EDGES };
    Section section = Section::NONE;

    std::string line;
    int lineNo = 0;

    auto fail = [this, &lineNo](const std::string& msg) -> bool {
        std::cerr << "Error on line " << lineNo << ": " << msg << "\n";
        clear();
        return false;
    };

    while (std::getline(in, line)) {
        ++lineNo;
        stripComment(line);
        trim(line);
        if (line.empty()) continue;

        if (line == "NODES") { section = Section::NODES; continue; }
        if (line == "EDGES") { section = Section::EDGES; continue; }

        if (section == Section::NONE) {
            return fail("data appeared before any NODES/EDGES header");
        }

        std::istringstream iss(line);

        if (section == Section::NODES) {
            int id;
            std::string name;
            if (!(iss >> id >> name)) {
                return fail("expected '<id> <name>'");
            }
            std::string extra;
            if (iss >> extra) {
                return fail("unexpected trailing token '" + extra +
                            "' (node names must be a single word)");
            }
            if (id < 0) {
                return fail("negative node id " + std::to_string(id));
            }
            if (idToName_.count(id)) {
                return fail("duplicate node id " + std::to_string(id));
            }
            if (nameToId_.count(name)) {
                return fail("duplicate node name '" + name + "'");
            }
            addNode(id, name);
        }
        else {
            int from, to;
            std::string modeTok;
            double dist, t, cost;

            if (!(iss >> from >> to >> modeTok >> dist >> t >> cost)) {
                return fail("expected '<from> <to> <MODE> <distance> <time> <cost>'");
            }
            std::string extra;
            if (iss >> extra) {
                return fail("unexpected trailing token '" + extra + "'");
            }
            if (!hasNode(from)) {
                return fail("unknown 'from' node id " + std::to_string(from));
            }
            if (!hasNode(to)) {
                return fail("unknown 'to' node id " + std::to_string(to));
            }
            TransportMode mode;
            if (!parseTransportMode(modeTok, mode)) {
                return fail("invalid mode '" + modeTok +
                            "' (expected BUS, METRO, or WALK)");
            }
            if (dist < 0.0 || t < 0.0 || cost < 0.0) {
                return fail("edge weights must be non-negative");
            }
            addEdge(from, to, dist, t, cost, mode, true);
        }
    }

    return true;
}
