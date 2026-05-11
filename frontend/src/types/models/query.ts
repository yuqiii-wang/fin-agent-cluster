/**
 * Node content models mirroring backend langgraph/models/query.py.
 * Used as the `content` payload inside BaseTaskInput/Output envelopes.
 */

export interface AnalyzeQueryInput {
  query: string;
}

export interface AnalyzeQueryOutput {
  intent: string;
  symbols: string[];
  filters: Record<string, unknown>;
}
