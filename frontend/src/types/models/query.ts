/**
 * Node content models mirroring backend langgraph/nodes/query_node models.
 * Used as the `content` payload inside BaseTaskInput/Output envelopes.
 */

export interface AnalyzeQueryInput {
  query: string;
}

export interface AnalyzeQueryOutput {
  stock_name: string;
  not_seen: boolean;
}

export interface WebStockInput {
  stock_name: string;
  query: string;
}

export interface WebStockOutput {
  url: string;
  title: string;
  content: string;
}

export interface GetStockRegionOutput {
  region: string;
}

export interface GetStockIndustryPeersOutput {
  industry: string;
  peers: string[];
}

export interface QueryNodeOutput {
  stock_name: string;
  region: string;
  industry: string;
  peers: string[];
}
