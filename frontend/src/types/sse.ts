/** SSE event shape pushed by the backend via Centrifugo. */

export interface SseEvent {
  event: string;
  thread_id?: string;
  node_id?: string;
  node_name?: string;
  task_id?: string;
  task_name?: string;
  status?: string;
  token?: string;
  seq?: number;
  total_tokens?: number;
  total_seq?: number;
  /** Present on ``ack_confirmed`` events — the ack_key that was confirmed. */
  ack_key?: string;
  [key: string]: unknown;
}
