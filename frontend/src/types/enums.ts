/** Status and type enums aligned to backend db/postgres/types.py */

/** Thread-level lifecycle status (maps to QueryStatus). */
export enum QueryStatus {
  Connecting = "connecting",
  Received = "received",
  Running = "running",
  Completed = "completed",
  Failed = "failed",
  Cancelled = "cancelled",
}

/** Node / task execution status (maps to WorkStatus). */
export enum WorkStatus {
  Pending = "pending",
  Running = "running",
  Completed = "completed",
  Failed = "failed",
  Cancelled = "cancelled",
  Wrong = "wrong",
}

/** Structural role of a node in the graph (maps to NodeType). */
export enum NodeType {
  Typical = "Typical",
  Reference = "Reference",
  Subgraph = "Subgraph",
}
