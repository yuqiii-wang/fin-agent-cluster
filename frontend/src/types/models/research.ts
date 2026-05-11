/**
 * Node content models mirroring backend langgraph/models/research.py.
 * Used as the `content` payload inside BaseTaskInput/Output envelopes.
 */

export interface ReadStatsInput {
  symbols: string[];
  interval: string;
}

export interface ReadStatsOutput {
  symbol: string;
  interval: string;
  records: Record<string, unknown>[];
}

export interface ReadNewsInput {
  symbols: string[];
}

export interface ReadNewsOutput {
  symbol: string;
  articles: Record<string, unknown>[];
}

export interface MergeResultsInput {
  stats_data: Record<string, unknown>;
  news_data: Record<string, unknown>;
}

export interface MergeResultsOutput {
  symbol: string;
  summary: string;
  stats: Record<string, unknown>;
  news: Record<string, unknown>;
}
