/**
 * Node content models mirroring backend langgraph/models/research.py.
 * Used as the `content` payload inside BaseTaskInput/Output envelopes.
 */

export interface ReadStatsInput {
  symbols: string[];
  interval: string;
}

/** Pandas split-orient DataFrame serialisation. */
export interface DfSplit {
  index: string[];
  columns: string[];
  data: number[][];
}

export interface ReadStatsOutput {
  symbol: string;
  interval: string;
  /** Pandas split-orient dict produced by matrix_to_split(). */
  df_split: DfSplit;
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
