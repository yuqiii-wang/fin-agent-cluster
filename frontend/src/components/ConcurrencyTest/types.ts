import type { QueryStatusValue, WorkStatusValue } from '../../constants/lifecycleStatus';

/** Per-thread tracking state for the concurrency test grid. */
export interface ThreadRow {
  threadId: string;
  /** Wall-clock ms when the request was submitted (Date.now()). */
  submitTime: number;
  /**
   * Thread-level status — mirrors backend QueryStatus enum.
   * 'pending' is a local UI-only initial state before any SSE arrives.
   * connecting | received | running | completed | failed | cancelled match the backend.
   */
  status: QueryStatusValue;
  /** Status of the stream_conclusion task under conclusion_node. */
  streamTaskStatus: WorkStatusValue | null;
  /** Whether the LLM-streaming Centrifugo MQ subscription is established. */
  llmMqConnected: boolean;
  /** Ms from submitTime to first conclusion_node running event. */
  latencyToConclusion: number | null;
  /** Total tokens received from LLM stream. */
  tokensReceived: number;
  /** Highest seq received (for gap detection). */
  maxSeq: number;
  /** Total expected tokens (from stream_end event). */
  totalSeq: number | null;
  /** Computed tokens-per-second over the last measurement window. */
  currentTps: number;
  /** Number of ACK messages sent to backend. */
  acksSent: number;
  /** Number of ACKs confirmed back from backend (ack_confirmed events). */
  acksConfirmed: number;
  /** Timestamp when streaming started (first token). */
  streamStart: number | null;
  /** Timestamp when streaming ended (stream_end event). */
  streamEnd: number | null;
}

export type ThreadRowUpdate = Partial<Omit<ThreadRow, 'threadId'>>;
