/**
 * cache — session-level UI cache for thread, node, and task data.
 *
 * Avoids redundant backend calls when the user revisits completed threads or
 * navigates away from and back to a finished streaming task.
 */

export { getCachedTaskOutput, setCachedTaskOutput, evictCachedTaskOutput } from './taskOutputCache';
export { getCachedThreadData, setCachedThreadData, evictThreadData } from './threadDataCache';
export type { ThreadCacheEntry } from './threadDataCache';
