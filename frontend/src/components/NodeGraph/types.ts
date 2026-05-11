import type { NodeInfo } from '../../types';

export type SingleSlot = { type: 'single'; node: NodeInfo };
export type ParallelSlot = { type: 'parallel'; group: string; nodes: NodeInfo[] };
export type InnerSlot = SingleSlot | ParallelSlot;

/** Visual kind for a directed edge. */
export type EdgeKind = 'sequential' | 'fan-out' | 'fan-in' | 'conditional';

export interface Bubble {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Layout {
  positions: Record<string, { x: number; y: number }>;
  svgW: number;
  topLevel: NodeInfo[];
  innerByParentId: Map<string, NodeInfo[]>;
  topEdges: Array<[string, string]>;
  innerEdges: Map<string, Array<[string, string, EdgeKind]>>;
  bubbles: Map<string, Bubble>;
}
