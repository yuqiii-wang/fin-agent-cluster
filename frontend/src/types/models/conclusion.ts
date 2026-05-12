/**
 * Node content models mirroring backend langgraph/models/conclusion.py.
 * Used as the `content` payload inside BaseTaskInput/Output envelopes.
 */

export interface StreamConclusionInput {
  merged_research: Record<string, unknown>;
  query: string;
}

export interface StreamConclusionOutput {
  answer: string;
  thinking?: string | null;
  total_tokens: number;
  latency_ms: number;
}
