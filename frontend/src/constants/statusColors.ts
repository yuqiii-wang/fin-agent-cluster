/**
 * Centralised status → colour mappings used across the UI.
 *
 * Four flavours:
 *  - STATUS_BADGE      antd Badge `status` prop values
 *  - STATUS_TAG_COLOR  antd Tag `color` prop values
 *  - STATUS_HEX        Raw hex colours (SVG / canvas node fills)
 *  - STATUS_DARK       Muted hex for timeline bar fill (default state)
 *  - STATUS_BRIGHT     Vivid hex for timeline bar fill (hover / active state)
 */

export const STATUS_BADGE: Record<string, 'processing' | 'success' | 'error' | 'warning' | 'default'> = {
  received:  'processing',
  running:   'processing',
  completed: 'success',
  failed:    'error',
  cancelled: 'warning',
  wrong:     'error',
};

export const STATUS_TAG_COLOR: Record<string, string> = {
  pending:    'default',
  connecting: 'default',
  received:   'cyan',
  running:    'processing',
  completed:  'success',
  failed:     'error',
  cancelled:  'warning',
  wrong:      'error',
};

export const STATUS_HEX: Record<string, string> = {
  pending:   '#8c8c8c',
  running:   '#1677ff',
  completed: '#52c41a',
  failed:    '#ff4d4f',
  cancelled: '#faad14',
  wrong:     '#d4380d',
};

export const STATUS_DARK: Record<string, string> = {
  pending:   '#2d2d2d',
  running:   '#0d2d52',
  completed: '#0f3020',
  failed:    '#3d1010',
  cancelled: '#3d2800',
};

export const STATUS_BRIGHT: Record<string, string> = {
  pending:   '#8c8c8c',
  running:   '#1677ff',
  completed: '#52c41a',
  failed:    '#ff4d4f',
  cancelled: '#faad14',
};
