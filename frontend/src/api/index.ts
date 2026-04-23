/** API helpers. All paths route through Kong API Gateway.
 *  Dev: Vite proxy forwards to Kong at localhost:8888.
 *  Prod: set VITE_KONG_URL=http://<host>:8888 at build time.
 */

export { KONG_ORIGIN, BASE } from "./config";
export { getStoredToken, getStoredUsername, guestLogin, fetchActiveThread, fetchHistory } from "./auth";
export { submitQuery, submitPerfQuery, fetchTasks, fetchNodeExecutions, cancelQuery, ackQuery } from "./queries";
export { createAckHandlers } from "./ack";
export { openStream, watchTask, fetchStreamingStatus } from "./stream";
export { cancelTask, passTask, fetchTaskMeta } from "./tasks";
export { fetchLatestReport, fetchReportById } from "./reports";
export { fetchQuantIndicators, fetchQuantStat, fetchSymbolCurrency } from "./quant";
