/**
 * Streaming error registry — frontend entry point.
 *
 * Exports:
 *  - {@link UI_STREAMING_ERRORS}  — browser / frontend-only error codes
 *  - {@link getErrorDescription}  — unified description lookup for any code
 *
 * Backend error codes are NOT re-exported from this module.  They arrive
 * inline in SSE event payloads as `error_code` + `error_description` fields,
 * and the full registry can be fetched from `GET /stream/errors`.
 */

export { UI_STREAMING_ERRORS } from "./ui";
import { UI_STREAMING_ERRORS } from "./ui";

/**
 * Return the human-readable description for any error code.
 *
 * Resolution order:
 *  1. Check {@link UI_STREAMING_ERRORS} (client-originated errors).
 *  2. Fall back to `inlineDescription` — the `error_description` field
 *     embedded by the backend in the SSE event payload (looked up server-side
 *     from the backend error registry).
 *
 * @param code              - The `error_code` string from an SSE event or
 *                            client-side action.  Pass `undefined` when no
 *                            code is available.
 * @param inlineDescription - Optional description already carried in the SSE
 *                            payload (`output.error_description` for `failed`
 *                            events; top-level `error_description` for `done`
 *                            events).
 * @returns The resolved description, or `undefined` if neither source has one.
 */
export function getErrorDescription(
  code: string | undefined,
  inlineDescription?: string,
): string | undefined {
  if (!code) return inlineDescription;

  // Check UI-side registry first (these are client-originated, never in backend).
  const uiDesc = UI_STREAMING_ERRORS[code];
  if (uiDesc) return uiDesc;

  // Fall back to the description embedded in the SSE payload by the backend.
  return inlineDescription;
}
