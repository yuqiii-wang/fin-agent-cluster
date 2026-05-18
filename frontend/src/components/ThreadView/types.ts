import type { DataViewerMode } from '../DataViewer/index';

/** State shape for the node detail data panel (Input/Output/stats viewer). */
export interface DetailData {
  label: string;
  data: unknown;
  mode?: DataViewerMode;
  viewSchema?: Record<string, string>;
  fieldList?: boolean;
  /** When set, the panel auto-follows node selection (input or output context). */
  nodeContext?: 'input' | 'output';
  /** Task ID for stream mode — DetailDataPanel resolves the live task from the tasks list. */
  taskId?: string;
}
