/** Shared Kong API Gateway base URL constants. */

// Base origin for Kong. Empty string in dev (Vite proxy), absolute URL in prod.
export const KONG_ORIGIN: string = (import.meta.env.VITE_KONG_URL as string | undefined) ?? "";
export const BASE = `${KONG_ORIGIN}/api/v1`;

// SSE origin — points at Kong's dedicated SSE port (8889 in dev) so that
// EventSource connections use a separate browser TCP pool from regular API calls
// (which go through localhost:3000 via Vite proxy).  Different host:port origins
// each get their own 6-connection HTTP/1.1 pool, removing the cap on concurrent
// SSE streams.  Set VITE_SSE_URL=http://localhost:8889 in .env.local.
export const SSE_ORIGIN: string = (import.meta.env.VITE_SSE_URL as string | undefined) ?? KONG_ORIGIN;
