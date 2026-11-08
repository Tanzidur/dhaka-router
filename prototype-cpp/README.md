# Adaptive Multi-Constraint City Routing System

CSE 373 — Design and Analysis of Algorithms
North South University, Spring 2026

This is the first prototype of [Dhaka Router](../README.md). Run the commands below from this folder.

## Build

Requires a C++17 compiler (g++ 7 or newer).

    g++ -std=c++17 -O2 -Wall -Wextra graph.cpp algorithms.cpp main.cpp -o router

On Windows with MSYS2/MinGW, the same command produces `router.exe`.

## Run

    ./router            (Linux/macOS)
    .\router.exe        (Windows)

A REPL prompt appears. Sample session:

    > load data/dhaka.map
    Loaded 6 nodes, 18 edges.

    > route Dhanmondi Uttara fastest
    Path:  Dhanmondi -> [BUS] -> Banani -> [METRO] -> Gulshan -> [METRO] -> Uttara
    Distance: 20.7 km   Time: 54.0 min   Cost: 125 BDT
    Computed in 2 us (5 nodes popped).

    > compare Dhanmondi Uttara
    ...

    > quit

## Commands

    load <path>                                Load a map file
    nodes                                      List all loaded nodes
    route <src> <dst> <mode> [opts...]         Compute a route
        mode: shortest | fastest | cheapest
              custom <alpha> <beta> <gamma>
        opts: avoid-node <name>                (repeatable)
              avoid-mode <BUS|METRO|WALK>      (repeatable)
    compare <src> <dst> [custom <a> <b> <c>]   Run all modes side-by-side
    help
    quit

## Files

    graph.h          Shared types and Graph class declaration
    graph.cpp        Graph implementation, map-file parser
    algorithms.h     Public interface for Dijkstra and route()
    algorithms.cpp   Dijkstra with pluggable weight function
    main.cpp         CLI / REPL
    data/dhaka.map   Sample input map
