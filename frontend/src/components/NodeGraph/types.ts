import type { NodeInfo } from '../../types';

export type SingleSlot = { type: 'single'; node: NodeInfo };
export type ParallelSlot = { type: 'parallel'; group: string; nodes: NodeInfo[] };
export type InnerSlot = SingleSlot | ParallelSlot;

/** Top-level slot types (may include conditional branch groups or parallel groups). */
export type TopSingleSlot = { type: 'single'; node: NodeInfo };
export type TopConditionalSlot = { type: 'conditional'; group: string; nodes: NodeInfo[] };
export type TopParallelSlot = { type: 'parallel'; group: string; nodes: NodeInfo[] };
export type TopSlot = TopSingleSlot | TopConditionalSlot | TopParallelSlot;

/** Visual kind for a directed edge. */
export type EdgeKind = 'sequential' | 'fan-out' | 'fan-in' | 'conditional' | 'cond-fan-out' | 'cond-fan-in';

export interface Bubble {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Layout {
  positions: Record<string, { x: number; y: number }>;
  svgW: number;
  svgH: number;
  topLevel: NodeInfo[];
  topSlots: TopSlot[];
  innerByParentId: Map<string, NodeInfo[]>;
  /** Each tuple carries the edge kind for proper conditional styling. */
  topEdges: Array<[string, string, EdgeKind]>;
  innerEdges: Map<string, Array<[string, string, EdgeKind]>>;
  bubbles: Map<string, Bubble>;
}
