/** Aggregated session status returned by GET /threads/{id}/tasks. */

import type { QueryResponse } from './thread';
import type { TaskInfo } from './task';

export interface SessionStatus {
  thread: QueryResponse;
  tasks: TaskInfo[];
}
