import type { CSSProperties } from "react";

// ── Font size primitives ──────────────────────────────────────────────

/** fontSize: 11 — secondary labels, icon text, helper chips */
export const FONT_XS: CSSProperties = { fontSize: 11 };

/** fontSize: 12 — metadata, timestamps, descriptive secondary text */
export const FONT_SM: CSSProperties = { fontSize: 12 };

// ── Monospace ─────────────────────────────────────────────────────────

export const MONO_FONT_FAMILY = "monospace" as const;

/** fontFamily: monospace, fontSize: 11 */
export const MONO_XS: CSSProperties = { fontFamily: MONO_FONT_FAMILY, fontSize: 11 };

// ── Layout helpers (spread and add gap / justifyContent as needed) ────

/** Horizontal flex row with vertical centering */
export const FLEX_ROW_CENTER: CSSProperties = { display: "flex", alignItems: "center" };

/** Vertical flex column */
export const FLEX_COL: CSSProperties = { display: "flex", flexDirection: "column" };
