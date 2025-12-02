from typing import Dict, List, Set, Optional
import logging

class DependencyGraph:
    def __init__(self):
        self.nodes: Set[str] = set()
        self.edges: Dict[str, List[str]] = {}  # key depends on values (key must run AFTER values)
        # Actually, for topological sort "A depends on B" usually means B comes before A.
        # So if we want execution order, and A has prerequisites [B, C], then B and C must run before A.
        # Edges: B -> A, C -> A.
        # Kahn's algorithm: nodes with in-degree 0 run first.
        # In-degree of A is 2. In-degree of B is 0.
        # So we store edges as: Prerequisite -> Dependent.
        
        self.prerequisites: Dict[str, List[str]] = {} # Node -> List of Prerequisites

    def add_node(self, name: str, prerequisites: List[str]):
        self.nodes.add(name)
        self.prerequisites[name] = prerequisites
        for prereq in prerequisites:
            self.nodes.add(prereq)

    def get_execution_order(self) -> List[str]:
        # Build adjacency list for Kahn's algorithm
        # Graph where edge U -> V means U must run before V.
        # So if V has prerequisite U, we add edge U -> V.
        adj: Dict[str, List[str]] = {node: [] for node in self.nodes}
        in_degree: Dict[str, int] = {node: 0 for node in self.nodes}

        for node, prereqs in self.prerequisites.items():
            for prereq in prereqs:
                adj[prereq].append(node)
                in_degree[node] += 1

        # Queue for nodes with no incoming edges (no prerequisites)
        queue = [node for node in self.nodes if in_degree[node] == 0]
        # Sort queue for deterministic output if multiple nodes are ready
        queue.sort()
        
        result = []
        
        while queue:
            u = queue.pop(0)
            result.append(u)
            
            for v in adj[u]:
                in_degree[v] -= 1
                if in_degree[v] == 0:
                    queue.append(v)
            
            # Keep queue sorted for determinism
            queue.sort()

        if len(result) != len(self.nodes):
            # Cycle detected
            logging.error("Cycle detected in dependency graph! Fallback to partial order.")
            # Return what we have, plus the remaining nodes in some arbitrary order (or error out)
            remaining = self.nodes - set(result)
            result.extend(sorted(list(remaining)))
            
        return result
