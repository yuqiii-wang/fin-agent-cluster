/** Shared Kong API Gateway base URL constants. */

// Base origin for Kong. Empty string in dev (Vite proxy), absolute URL in prod.
export const KONG_ORIGIN: string = (import.meta.env.VITE_KONG_URL as string | undefined) ?? "";
export const BASE = `${KONG_ORIGIN}/api/v1`;
