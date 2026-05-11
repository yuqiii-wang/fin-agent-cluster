/**
 * DataViewer — unified data display component.
 *
 * Modes:
 *  - json:     display `data` as formatted JSON (JsonViewer).
 *  - stream:   live or completed LLM token stream (StreamViewer).
 *  - markdown: render `text` as markdown (MarkdownViewer).
 */

import React from 'react';
import JsonViewer from './JsonViewer';
import MarkdownViewer from './MarkdownViewer';
import StreamViewer from './StreamViewer';
import type { StreamViewerProps } from './StreamViewer';
import type { TaskInfo } from '../../types';

export type DataViewerMode = 'json' | 'stream' | 'markdown';

export interface DataViewerProps extends StreamViewerProps {
  mode: DataViewerMode;
  /** JSON data to display (mode="json"). */
  data?: unknown;
  /** Task context — enables per-task subscription fallback (mode="stream"). */
  task?: TaskInfo;
  /** Thread ID for the per-task subscription fallback. */
  threadId?: string;
  /**
   * When provided and the stream has completed with a thinking section,
   * the answer portion is sent here for display in the bottom DataViewer panel.
   */
  onViewData?: (label: string, data: unknown) => void;
  /** Called once when the stream finishes. */
  onStreamEnd?: () => void;
  maxHeight?: number;
  style?: React.CSSProperties;
}

const DataViewer: React.FC<DataViewerProps> = ({
  mode,
  data,
  text,
  isLive,
  task,
  threadId,
  onViewData: _onViewData,
  onStreamEnd,
  maxHeight = 320,
  style,
}) => {
  if (mode === 'json') {
    return <JsonViewer data={data} maxHeight={maxHeight} style={style} />;
  }

  if (mode === 'markdown') {
    return <MarkdownViewer text={text} maxHeight={maxHeight} style={style} />;
  }

  return (
    <StreamViewer
      text={text}
      isLive={isLive}
      task={task}
      threadId={threadId}
      onStreamEnd={onStreamEnd}
      maxHeight={maxHeight}
      style={style}
    />
  );
};

export default DataViewer;
