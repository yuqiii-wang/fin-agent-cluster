import type { NodeInfo, GraphTopology } from '../../types';

/** BFS to collect all transitive predecessor node IDs starting from a set of IDs. */
export function collectPredecessors(startIds: string[], nodeById: Map<string, NodeInfo>): Set<string> {
  const visited = new Set<string>();
  const queue = [...startIds];
  while (queue.length > 0) {
    const id = queue.shift()!;
    if (visited.has(id)) continue;
    const n = nodeById.get(id);
    if (!n) continue;
    visited.add(id);
    for (const pid of n.prev_node_ids ?? []) {
      if (!visited.has(pid)) queue.push(pid);
    }
  }
  return visited;
}

/** Filter the full merged node list down to what should be visible for a given version.
 *  For fork versions, also includes inner nodes of any shared Subgraph nodes so that
 *  the NodeDetail subgraph panel can display their children.
 *  Topology-only placeholder nodes are included for both v0 and fork versions so that:
 *  - conditional branch peers (same conditional_group) render dashed edges correctly
 *  - +1 depth not-yet-run nodes are visible as grey placeholders */
export function getNodesForVersion(allNodes: NodeInfo[], version: number, topology?: GraphTopology | null): NodeInfo[] {
  if (version === 0) {
    // Original run: version-0 real nodes + topology-only placeholders
    return allNodes.filter(n => n.is_topology_only || (n.version ?? 0) === 0);
  }
  // Fork branch: version-N real nodes + shared predecessors
  const realNodes = allNodes.filter(n => !n.is_topology_only);
  const topologyOnlyNodes = allNodes.filter(n => n.is_topology_only);
  const nodeById = new Map(realNodes.map(n => [n.node_id, n]));
  const forkNode = realNodes.find(n => n.is_forked && (n.version ?? 0) === version);
  const versionNNodes = realNodes.filter(n => (n.version ?? 0) === version);
  if (!forkNode) return versionNNodes;
  const sharedIds = collectPredecessors(forkNode.prev_node_ids ?? [], nodeById);
  const sharedNodes = realNodes.filter(n => sharedIds.has(n.node_id));
  // BFS: also include inner nodes (children) of any shared Subgraph nodes.
  const allSharedIds = new Set(sharedIds);
  let frontier = sharedNodes.filter(n => n.type === 'Subgraph').map(n => n.node_id);
  while (frontier.length > 0) {
    const next: string[] = [];
    for (const parentId of frontier) {
      for (const n of realNodes) {
        if (n.parent_node_id === parentId && !allSharedIds.has(n.node_id)) {
          allSharedIds.add(n.node_id);
          if (n.type === 'Subgraph') next.push(n.node_id);
        }
      }
    }
    frontier = next;
  }
  // Also include parallel siblings: nodes that appear in version-N nodes' prev_node_ids
  // and share a parallel_group with a version-N node (but are not themselves version-N).
  const parallelGroupsInVersionN = new Set(
    versionNNodes.map(n => n.parallel_group).filter((g): g is string => g != null));
  if (parallelGroupsInVersionN.size > 0) {
    const versionNPrevIds = new Set(versionNNodes.flatMap(n => n.prev_node_ids ?? []));
    for (const n of realNodes) {
      if (
        !allSharedIds.has(n.node_id) &&
        !versionNNodes.some(v => v.node_id === n.node_id) &&
        n.parallel_group != null &&
        parallelGroupsInVersionN.has(n.parallel_group) &&
        versionNPrevIds.has(n.node_id)
      ) {
        allSharedIds.add(n.node_id);
      }
    }
  }
  const allSharedNodes = realNodes.filter(n => allSharedIds.has(n.node_id));
  const includedRealNodes = [...allSharedNodes, ...versionNNodes];

  if (topologyOnlyNodes.length === 0) return includedRealNodes;

  // Build successor set from topology edges so we can reveal +1 depth placeholders.
  const includedNames = new Set(includedRealNodes.map(n => n.node_name));
  const successorTopoNames = new Set<string>();
  if (topology) {
    for (const edge of topology.edges) {
      if (includedNames.has(edge.from_node) && !includedNames.has(edge.to_node)) {
        successorTopoNames.add(edge.to_node);
      }
    }
  }

  // Include topology-only nodes that are:
  //   (a) direct successors of included real nodes (+1 depth not-run nodes), or
  //   (b) conditional peers of an included real node (same conditional_group), or
  //   (c) parallel peers of an included real node (same parallel_group).
  const relevantTopoNodes = topologyOnlyNodes.filter(n =>
    successorTopoNames.has(n.node_name) ||
    (n.conditional_group != null &&
      includedRealNodes.some(r => r.conditional_group === n.conditional_group)) ||
    (n.parallel_group != null &&
      includedRealNodes.some(r => r.parallel_group === n.parallel_group)),
  );
  return [...includedRealNodes, ...relevantTopoNodes];
}
