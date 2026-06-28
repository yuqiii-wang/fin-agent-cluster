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

/** Resolve the effective parallel group for a node, consulting both the
 *  runtime value on the NodeInfo and the topology definition.  Runtime nodes
 *  whose topology declares `align_with_node_name` get their `parallel_group`
 *  stripped by `mergeWithTopology` (because layout alignment takes priority),
 *  so we fall back to the topology's own parallel_group for group membership
 *  tests such as "include sibling spurs in a re-explored branch".  For nodes
 *  that declare only an `align_with_node_name` (e.g. `load_peers_stats`), we
 *  further inherit the parallel_group of the alignment target — the whole
 *  prepare_peers → load_peers_stats chain belongs to the same fan-out group. */
function getEffectiveParallelGroup(n: NodeInfo, topology: GraphTopology | null | undefined): string | null {
  if (n.parallel_group) return n.parallel_group;
  if (!topology) return null;
  for (const t of topology.nodes) {
    if (t.node_name !== n.node_name) continue;
    if (t.parallel_group) return t.parallel_group;
    if (t.align_with_node_name) {
      for (const s of topology.nodes) {
        if (s.node_name === t.align_with_node_name && s.parallel_group) {
          return s.parallel_group;
        }
      }
    }
  }
  return null;
}

/** Resolve the effective `align_with_node_name` reference for a node, again
 *  consulting both runtime and topology so topology-only placeholders and
 *  alignment-stripped runtime nodes are treated consistently. */
function getEffectiveAlignWith(n: NodeInfo, topology: GraphTopology | null | undefined): string | null {
  if (n.align_with_node_name) return n.align_with_node_name;
  if (!topology) return null;
  for (const t of topology.nodes) {
    if (t.node_name === n.node_name && t.align_with_node_name) return t.align_with_node_name;
  }
  return null;
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
  // Also include parallel siblings: nodes that share a parallel_group with a version-N node
  // and branch off from a shared ancestor (at least one predecessor is already in allSharedIds).
  // These are sibling nodes in the same fan-out group, NOT predecessors of the forked node.
  // Exclude any node whose node_name matches a version-N node name — that is the "old version"
  // of the same node, which must not appear alongside the new forked copy.
  //
  // NOTE: we use getEffectiveParallelGroup so continuation nodes like `load_peers_stats`
  // (whose topology declares align_with_node_name="prepare_peers" and whose runtime
  // parallel_group was stripped by mergeWithTopology) are still recognised as members
  // of the "analyze_parallel" fan-out group.
  const parallelGroupsInVersionN = new Set<string>();
  for (const n of versionNNodes) {
    const g = getEffectiveParallelGroup(n, topology);
    if (g) parallelGroupsInVersionN.add(g);
  }
  const versionNNodeNames = new Set(versionNNodes.map(n => n.node_name));
  if (parallelGroupsInVersionN.size > 0) {
    for (const n of realNodes) {
      if (allSharedIds.has(n.node_id)) continue;
      if (versionNNodeNames.has(n.node_name)) continue;
      const group = getEffectiveParallelGroup(n, topology);
      if (!group) continue;
      if (!parallelGroupsInVersionN.has(group)) continue;
      if (!(n.prev_node_ids ?? []).some(pid => allSharedIds.has(pid))) continue;
      allSharedIds.add(n.node_id);
    }
  }

  // Include nodes whose align_with_node_name target (the "continuation" predecessor)
  // is already in allSharedIds.  This guarantees the topology-only placeholder for
  // nodes like `load_peers_stats` (continuation of `prepare_peers`) is rendered even
  // when the fork happened on a different parallel spur.  Also carry alignment the
  // other direction: if a node that IS an alignment target is included, include its
  // aligned continuation if that continuation has also run at some version.
  const alignedContinuationByName = new Map<string, string>();
  if (topology) {
    for (const t of topology.nodes) {
      if (t.align_with_node_name) {
        alignedContinuationByName.set(t.align_with_node_name, t.node_name);
      }
    }
  }
  let changed = true;
  while (changed) {
    changed = false;
    const includedNames = new Set<string>();
    for (const n of realNodes) {
      if (allSharedIds.has(n.node_id)) includedNames.add(n.node_name);
    }
    for (const n of realNodes) {
      if (allSharedIds.has(n.node_id)) continue;
      if (versionNNodeNames.has(n.node_name)) continue;
      const alignRef = getEffectiveAlignWith(n, topology);
      if (alignRef && includedNames.has(alignRef)) {
        allSharedIds.add(n.node_id);
        changed = true;
        continue;
      }
      const continuation = alignedContinuationByName.get(n.node_name);
      if (continuation && includedNames.has(continuation)) {
        allSharedIds.add(n.node_id);
        changed = true;
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
