#include "algorithms.h"
#include "graph.h"

#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#endif

namespace {

std::vector<std::string> tokenize(const std::string& line) {
    std::vector<std::string> tokens;
    std::istringstream iss(line);
    std::string tok;
    while (iss >> tok) tokens.push_back(tok);
    return tokens;
}

void printPath(const Graph& g, const RouteResult& r) {
    std::cout << "Path:  ";
    for (std::size_t i = 0; i < r.path.size(); ++i) {
        if (i > 0) {
            std::cout << " \xE2\x86\x92 [" << transportModeToString(r.modes[i - 1]) << "] \xE2\x86\x92 ";
        }
        std::cout << g.nameOf(r.path[i]);
    }
    std::cout << "\n";
}

void printResult(const Graph& g, const RouteResult& r) {
    if (!r.found) {
        std::cout << "No path found.\n";
        std::cout << "(Searched in " << r.executionMicros << " us, "
                  << r.nodesPopped << " nodes popped.)\n";
        return;
    }
    printPath(g, r);
    std::cout << std::fixed;
    std::cout << "Distance: " << std::setprecision(1) << r.totalDistance << " km   "
              << "Time: "     << std::setprecision(1) << r.totalTime     << " min   "
              << "Cost: "     << std::setprecision(0) << r.totalCost     << " BDT\n";
    std::cout.unsetf(std::ios::fixed);
    std::cout << "Computed in " << r.executionMicros << " us ("
              << r.nodesPopped << " nodes popped).\n";
}

void cmdHelp() {
    std::cout <<
        "Commands:\n"
        "  load <path>                            Load a map file\n"
        "  nodes                                  List all loaded nodes\n"
        "  route <src> <dst> <mode> [opts...]     Compute a route\n"
        "      mode: shortest | fastest | cheapest\n"
        "            custom <alpha> <beta> <gamma>\n"
        "      opts: avoid-node <name>            (repeatable)\n"
        "            avoid-mode <BUS|METRO|WALK>  (repeatable)\n"
        "  compare <src> <dst> [custom <a> <b> <c>]\n"
        "                                         Run all modes side-by-side\n"
        "  help                                   This help\n"
        "  quit                                   Exit\n";
}

void cmdLoad(Graph& g, const std::vector<std::string>& tokens) {
    if (tokens.size() != 2) {
        std::cout << "Usage: load <path>\n";
        return;
    }
    if (g.loadFromFile(tokens[1])) {
        std::cout << "Loaded " << g.nodeCount() << " nodes, "
                  << g.edgeCount() << " edges.\n";
    }
}

void cmdNodes(const Graph& g) {
    if (g.nodeCount() == 0) {
        std::cout << "No map loaded. Use: load <path>\n";
        return;
    }
    std::cout << "Loaded " << g.nodeCount() << " nodes:\n";
    for (int i = 0; i < g.nodeCount(); ++i) {
        if (g.hasNode(i)) {
            std::cout << "  " << i << "  " << g.nameOf(i) << "\n";
        }
    }
}

bool parseRouteMode(const std::string& s, RouteMode& mode) {
    if (s == "shortest" || s == "distance") { mode = RouteMode::SHORTEST_DISTANCE; return true; }
    if (s == "fastest"  || s == "time")     { mode = RouteMode::FASTEST;           return true; }
    if (s == "cheapest" || s == "cost")     { mode = RouteMode::CHEAPEST;          return true; }
    if (s == "custom")                      { mode = RouteMode::CUSTOM;            return true; }
    return false;
}

// Parses three coefficients starting at tokens[from].
// Returns the index past the last consumed token, or 0 on failure.
std::size_t parseCustomCoeffs(const std::vector<std::string>& tokens,
                              std::size_t from, WeightConfig& cfg) {
    if (tokens.size() < from + 3) {
        std::cout << "custom requires three coefficients: alpha beta gamma\n";
        return 0;
    }
    try {
        cfg.alpha = std::stod(tokens[from]);
        cfg.beta  = std::stod(tokens[from + 1]);
        cfg.gamma = std::stod(tokens[from + 2]);
    } catch (...) {
        std::cout << "custom coefficients must be numbers\n";
        return 0;
    }
    if (cfg.alpha < 0 || cfg.beta < 0 || cfg.gamma < 0) {
        std::cout << "custom coefficients must be non-negative "
                  << "(Dijkstra requires non-negative edge weights).\n";
        return 0;
    }
    return from + 3;
}

void cmdRoute(const Graph& g, const std::vector<std::string>& tokens) {
    if (g.nodeCount() == 0) {
        std::cout << "No map loaded. Use: load <path>\n";
        return;
    }
    if (tokens.size() < 4) {
        std::cout << "Usage: route <src> <dst> <mode> [opts...]\n"
                  << "       route <src> <dst> custom <a> <b> <c> [opts...]\n";
        return;
    }
    int src = g.idOf(tokens[1]);
    int dst = g.idOf(tokens[2]);
    if (src < 0) { std::cout << "Unknown source: "      << tokens[1] << "\n"; return; }
    if (dst < 0) { std::cout << "Unknown destination: " << tokens[2] << "\n"; return; }

    RouteMode mode;
    if (!parseRouteMode(tokens[3], mode)) {
        std::cout << "Unknown mode: " << tokens[3]
                  << " (expected shortest, fastest, cheapest, or custom)\n";
        return;
    }

    WeightConfig cfg;
    std::size_t i = 4;
    if (mode == RouteMode::CUSTOM) {
        i = parseCustomCoeffs(tokens, 4, cfg);
        if (i == 0) return;
    }

    Constraints cons;
    while (i < tokens.size()) {
        const std::string& opt = tokens[i];
        if (opt == "avoid-node") {
            if (i + 1 >= tokens.size()) {
                std::cout << "avoid-node requires a node name\n"; return;
            }
            int nid = g.idOf(tokens[i + 1]);
            if (nid < 0) {
                std::cout << "Unknown node: " << tokens[i + 1] << "\n"; return;
            }
            cons.avoidNodes.insert(nid);
            i += 2;
        } else if (opt == "avoid-mode") {
            if (i + 1 >= tokens.size()) {
                std::cout << "avoid-mode requires BUS, METRO, or WALK\n"; return;
            }
            TransportMode m;
            if (!parseTransportMode(tokens[i + 1], m)) {
                std::cout << "Unknown mode: " << tokens[i + 1]
                          << " (expected BUS, METRO, or WALK)\n";
                return;
            }
            cons.avoidModes.insert(m);
            i += 2;
        } else {
            std::cout << "Unknown option: " << opt << "\n";
            return;
        }
    }

    RouteResult r = route(g, src, dst, mode, cfg, cons);
    printResult(g, r);
}

void printCompareHeader() {
    using std::setw; using std::left; using std::right;
    std::cout << left  << setw(24) << "Mode"
              << right << setw(8)  << "Hops"
                       << setw(12) << "Time(min)"
                       << setw(12) << "Cost(BDT)"
                       << setw(14) << "Distance(km)"
                       << setw(10) << "us"
                       << setw(14) << "Nodes popped" << "\n";
    std::cout << std::string(94, '-') << "\n";
}

void printCompareRow(const std::string& label, const RouteResult& r) {
    using std::setw; using std::left; using std::right;
    using std::fixed; using std::setprecision;

    std::cout << left << setw(24) << label;
    if (!r.found) {
        std::cout << right << setw(8)  << "-"
                           << setw(12) << "-"
                           << setw(12) << "-"
                           << setw(14) << "-"
                           << setw(10) << r.executionMicros
                           << setw(14) << r.nodesPopped << "\n";
        return;
    }
    std::cout << right << setw(8) << (r.path.size() - 1)
                       << fixed
                       << setprecision(1) << setw(12) << r.totalTime
                       << setprecision(0) << setw(12) << r.totalCost
                       << setprecision(1) << setw(14) << r.totalDistance;
    std::cout.unsetf(std::ios::fixed);
    std::cout << setw(10) << r.executionMicros
              << setw(14) << r.nodesPopped << "\n";
}

void cmdCompare(const Graph& g, const std::vector<std::string>& tokens) {
    if (g.nodeCount() == 0) {
        std::cout << "No map loaded. Use: load <path>\n";
        return;
    }
    if (tokens.size() < 3) {
        std::cout << "Usage: compare <src> <dst> [custom <a> <b> <c>]\n";
        return;
    }
    int src = g.idOf(tokens[1]);
    int dst = g.idOf(tokens[2]);
    if (src < 0) { std::cout << "Unknown source: "      << tokens[1] << "\n"; return; }
    if (dst < 0) { std::cout << "Unknown destination: " << tokens[2] << "\n"; return; }

    bool runCustom = false;
    WeightConfig cfg;
    if (tokens.size() >= 4) {
        if (tokens[3] != "custom") {
            std::cout << "Unexpected token: " << tokens[3]
                      << " (compare takes optional 'custom <a> <b> <c>')\n";
            return;
        }
        if (parseCustomCoeffs(tokens, 4, cfg) == 0) return;
        runCustom = true;
    }

    Constraints cons;

    printCompareHeader();
    printCompareRow("Shortest distance",
        route(g, src, dst, RouteMode::SHORTEST_DISTANCE, {}, cons));
    printCompareRow("Fastest",
        route(g, src, dst, RouteMode::FASTEST, {}, cons));
    printCompareRow("Cheapest",
        route(g, src, dst, RouteMode::CHEAPEST, {}, cons));
    if (runCustom) {
        std::ostringstream lbl;
        lbl << "Custom (" << cfg.alpha << ", " << cfg.beta << ", " << cfg.gamma << ")";
        printCompareRow(lbl.str(),
            route(g, src, dst, RouteMode::CUSTOM, cfg, cons));
    }
}

}  // namespace

int main() {
#ifdef _WIN32
    SetConsoleOutputCP(CP_UTF8);
#endif

    Graph g;
    std::cout << "Adaptive Multi-Constraint City Routing System\n";
    std::cout << "Type 'help' for commands, 'quit' to exit.\n";

    std::string line;
    while (true) {
        std::cout << "> " << std::flush;
        if (!std::getline(std::cin, line)) {
            std::cout << "\n";
            break;
        }

        auto tokens = tokenize(line);
        if (tokens.empty()) continue;

        const std::string& cmd = tokens[0];
        if      (cmd == "quit" || cmd == "exit") break;
        else if (cmd == "help")    cmdHelp();
        else if (cmd == "load")    cmdLoad(g, tokens);
        else if (cmd == "nodes")   cmdNodes(g);
        else if (cmd == "route")   cmdRoute(g, tokens);
        else if (cmd == "compare") cmdCompare(g, tokens);
        else std::cout << "Unknown command: " << cmd << ". Type 'help'.\n";
    }
    return 0;
}
