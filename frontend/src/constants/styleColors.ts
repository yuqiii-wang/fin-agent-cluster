/**
 * Centralised raw colour tokens for the dark-mode UI.
 *
 * Import specific tokens rather than reaching for inline hex literals.
 * Status-driven colours live in statusColors.ts; this file covers
 * structural / chrome colours.
 */

// ── Brand ─────────────────────────────────────────────────────────────────
export const COLOR_BRAND_BLUE = '#1677ff';

// ── Surface backgrounds ────────────────────────────────────────────────────
export const COLOR_SURFACE_DEEP   = '#0e0e0e'; // Gantt task track
export const COLOR_SURFACE_BASE   = '#141414'; // Timeline bar track, DataViewer pre/mdBox
export const COLOR_SURFACE_RAISED = '#1a1a1a'; // SubgraphNode hover bg
export const COLOR_SURFACE_CARD   = '#1f1f1f'; // ThreadView splitter border

// ── Borders / dividers ────────────────────────────────────────────────────
export const COLOR_BORDER_STRONG    = '#000000'; // Node segment right-edge
export const COLOR_BORDER_BASE      = '#303030'; // DataViewer pre / mdBox border
export const COLOR_BORDER_SUBTLE    = '#262626'; // DataViewer thinking-panel border
export const COLOR_BORDER_PANEL     = '#1f1f1f'; // Splitter panel separator

// ── Axis / grid ticks ────────────────────────────────────────────────────
export const COLOR_TICK_MAIN   = '#1e1e1e'; // Main bar-row grid line
export const COLOR_TICK_TASK   = '#1a1a1a'; // Task Gantt grid line

// ── Text ─────────────────────────────────────────────────────────────────
export const COLOR_TEXT_BRIGHT     = '#ffffff'; // Inline elapsed on lit segments
export const COLOR_TEXT_ACTIVE     = '#cccccc'; // Hovered label
export const COLOR_TEXT_BODY       = '#d9d9d9'; // DataViewer pre body text
export const COLOR_TEXT_SECONDARY  = '#8c8c8c'; // Section headings, thinking label
export const COLOR_TEXT_DIM        = '#666666'; // Parallel-expanded row group label
export const COLOR_TEXT_MUTED      = '#595959'; // Default label, copyable code
export const COLOR_TEXT_FAINT      = '#444444'; // Un-hovered row label
export const COLOR_TEXT_TASK_HOV   = '#bbbbbb'; // Task label on hover
export const COLOR_TEXT_TASK_DIM   = '#484848'; // Task label default

// ── Node graph ───────────────────────────────────────────────────────────
export const COLOR_GRAPH_ARROW         = '#aaaaaa'; // Edge / arrow fill
export const COLOR_GRAPH_FALLBACK_NODE = '#d9d9d9'; // Node circle when no status
export const COLOR_GRAPH_LABEL_TEXT    = '#e0e0e0'; // Node name label
export const COLOR_GRAPH_ELAPSED_TEXT  = '#ffffff'; // Elapsed text inside node
export const COLOR_GRAPH_SELECTED_RING = '#ffffff'; // Selected circle stroke
export const COLOR_GRAPH_RUNNING_RING  = COLOR_BRAND_BLUE; // Pulse ring stroke
export const COLOR_GRAPH_SUBGRAPH_FILL   = 'rgba(22,119,255,0.05)';
export const COLOR_GRAPH_SUBGRAPH_STROKE = 'rgba(22,119,255,0.3)';
export const COLOR_GRAPH_SELECTED_GLOW  = 'rgba(255,255,255,0.8)';

// ── Node subgraph top-border indicator ────────────────────────────────────
export const COLOR_SUBGRAPH_INDICATOR_DIM = '#555555';

// ── Semantic status ─────────────────────────────────────────────────────
export const COLOR_DANGER               = '#ff4d4f'; // Error / danger border/highlight
export const COLOR_STATUS_DARK_FALLBACK = '#2d2d2d'; // Fallback dark bg for unknown status

// ── Timeline overlap highlight ────────────────────────────────────────────
export const COLOR_OVERLAP_FILL   = 'rgba(255, 220, 80, 0.18)';
export const COLOR_OVERLAP_BORDER = 'rgba(255, 220, 80, 0.45)';

// ── Accent colours ────────────────────────────────────────────────────────
export const COLOR_ACCENT_PURPLE = '#722ed1'; // Skill indicator / hardcoded skill lock icon
export const COLOR_STATUS_SUCCESS = '#52c41a'; // Bound-tool check / success indicator

// ── Subtle / transparent variants ─────────────────────────────────────────
export const COLOR_BRAND_BLUE_SUBTLE = '#1677ff33'; // Brand blue at low opacity (active entry border)
export const COLOR_BORDER_INACTIVE   = '#333333';   // Inactive / forgotten entry border

// ── Chart: volatility smile ───────────────────────────────────────────────
export const COLOR_CHART_CALL_IV    = '#60a5fa'; // blue-400 – call IV line
export const COLOR_CHART_PUT_IV     = '#fb923c'; // orange-400 – put IV line
export const COLOR_CHART_GRID       = '#2B2F38'; // chart grid lines
export const COLOR_CHART_AXIS       = '#9B9EA4'; // axis labels / lines / text
export const COLOR_CHART_BG         = '#1a1d23'; // chart background
export const COLOR_CHART_ATM        = '#a3e635'; // lime – ATM vertical line
export const COLOR_CHART_TOOLTIP_BG = '#1e2330'; // tooltip / legend box fill
export const COLOR_HOVER_CROSSHAIR  = '#ffffff40'; // chart hover crosshair line

// ── Parallel-expand toggle ────────────────────────────────────────────────
export const COLOR_PARALLEL_ACTIVE   = '#faad14';
export const COLOR_PARALLEL_INACTIVE = '#595959';
