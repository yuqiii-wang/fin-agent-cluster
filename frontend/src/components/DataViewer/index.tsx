/**
 * DataViewer — unified data display component.
 *
 * Modes:
 *  - json:       display `data` as formatted JSON (JsonViewer).
 *  - stream:     live or completed LLM token stream (StreamViewer).
 *  - markdown:   render `text` as markdown (MarkdownViewer).
 *  - dataframe:  render a pandas split-orient df_split as an antd Table (StatsDataFrame).
 *  - mirror:     render output from a referenced task (data = {task_id}).
 *  - hybrid:     render multiple fields each with their own view type (uses viewSchema).
 */

import React, { useState, useMemo } from 'react';
import { Collapse, Typography } from 'antd';
import JsonViewer from './JsonViewer';
import MarkdownViewer from './MarkdownViewer';
import StreamViewer from './StreamViewer';
import StatsDataFrame from './StatsDataFrame';
import StatsViewer, { StatsViewSelect } from './StatsViewer';
import StackCandleStickChart from './StatsViewer/StackCandleStickChart';
import type { StackCandleItem } from './StatsViewer/StackCandleStickChart';
import WebRequestViewer from './WebRequestViewer';
import type { StreamViewerProps } from './StreamViewer';
import type { DfSplit } from './StatsDataFrame';
import type { TaskInfo } from '../../types';

const { Text } = Typography;

export type DataViewerMode = 'json' | 'stream' | 'markdown' | 'dataframe' | 'mirror' | 'hybrid' | 'webrequest';

/** Map a backend view_type string to a DataViewerMode. */
export function viewTypeToMode(viewType: string | undefined): DataViewerMode {
  switch (viewType) {
    case 'Streaming': return 'stream';
    case 'Stats': return 'dataframe';
    case 'Markdown': return 'markdown';
    case 'Mirror': return 'mirror';
    case 'Hybrid': return 'hybrid';
    case 'WebRequest': return 'webrequest';
    default: return 'json';
  }
}

export interface DataViewerProps extends StreamViewerProps {
  mode: DataViewerMode;
  /** JSON data to display (mode="json") or the raw node output for mirror/hybrid. */
  data?: unknown;
  /**
   * Per-field view type schema for hybrid nodes.
   * Shape: { fieldName: "ViewType" | "Mirror" }
   */
  viewSchema?: Record<string, unknown>;
  /** All tasks in the thread — used to resolve Mirror references. */
  tasks?: TaskInfo[];
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
  /**
   * When true, render all top-level fields as a Collapse list (all collapsed by default).
   * For json: top-level object keys. For hybrid: schema fields. For mirror: resolved task fields.
   * For stream/markdown/dataframe: single collapsed panel.
   */
  fieldList?: boolean;
  /**
   * Active stats view type (e.g. 'DataFrame', 'CandleStick') — controlled by the parent
   * panel header Select. Only used for non-fieldList dataframe mode.
   */
  activeStatsView?: string;
}

/** Render a single field according to its view type, resolving Mirror via tasks. */
function FieldViewer({
  fieldViewType,
  fieldData,
  tasks = [],
  threadId,
  maxHeight,
  style,
  _resolvedTask,
  activeStatsView,
}: {
  fieldViewType: string;
  fieldData: unknown;
  tasks?: TaskInfo[];
  threadId?: string;
  maxHeight?: number;
  style?: React.CSSProperties;
  /** Pre-resolved TaskInfo passed down from a parent Mirror resolution. */
  _resolvedTask?: TaskInfo;
  /** Controlled stats view type, passed from the parent Collapse header Select. */
  activeStatsView?: string;
}) {
  const mode = viewTypeToMode(fieldViewType);

  if (mode === 'mirror') {
    const taskId = (fieldData as Record<string, unknown> | undefined)?.task_id as string | undefined;
    const resolvedTask = taskId ? tasks.find((t) => t.task_id === taskId) : undefined;
    if (!resolvedTask) {
      return <Text type="secondary">Mirror ref not resolved (task_id: {taskId ?? '—'})</Text>;
    }
    return (
      <FieldViewer
        fieldViewType={resolvedTask.view_type ?? 'Json'}
        fieldData={resolvedTask.output}
        tasks={tasks}
        threadId={threadId}
        maxHeight={maxHeight}
        style={style}
        _resolvedTask={resolvedTask}
        activeStatsView={activeStatsView}
      />
    );
  }

  if (mode === 'dataframe') {
    const dataObj = fieldData as Record<string, unknown> | undefined;
    const dfSplits = dataObj?.df_splits as StackCandleItem[] | undefined;
    const dfSplit = dataObj?.df_split as DfSplit | undefined;
    const statsViews = dataObj?.stats_views as string[] | undefined;
    if (dfSplits?.length && statsViews?.includes('StackCandleStick')) {
      return <StackCandleStickChart items={dfSplits} />;
    }
    if (dfSplit && statsViews?.length) {
      return <StatsViewer dfSplit={dfSplit} activeView={activeStatsView ?? statsViews[0]} maxHeight={maxHeight} symbol={dataObj?.symbol as string | undefined} />;
    }
    return dfSplit
      ? <StatsDataFrame dfSplit={dfSplit} maxHeight={maxHeight} />
      : <JsonViewer data={fieldData} maxHeight={maxHeight} style={style} />;
  }

  if (mode === 'markdown') {
    return <MarkdownViewer text={fieldData as string | undefined} maxHeight={maxHeight} style={style} />;
  }

  if (mode === 'stream') {
    // When reached via a parent Mirror resolution, _resolvedTask already holds the correct
    // TaskInfo (with output.thinking populated from the DB). Otherwise look up by task_id.
    const streamTask =
      _resolvedTask ??
      tasks.find((t) => (fieldData as Record<string, unknown> | undefined)?.task_id === t.task_id);
    return (
      <StreamViewer
        text={typeof fieldData === 'string' ? fieldData : undefined}
        task={streamTask}
        threadId={threadId}
        maxHeight={maxHeight}
        style={style}
      />
    );
  }

  if (mode === 'webrequest') {
    return <WebRequestViewer data={fieldData} maxHeight={maxHeight} style={style} />;
  }

  return <JsonViewer data={fieldData} maxHeight={maxHeight} style={style} />;
}

/** Collapse panel for fieldList stats output: manages activeView state and shows Select in the panel label. */
const StatsFieldListCollapse: React.FC<{
  dfSplit: DfSplit;
  statsViews: string[];
  maxHeight: number;
  style?: React.CSSProperties;
  symbol?: string;
}> = ({ dfSplit, statsViews, maxHeight, style, symbol }) => {
  const [activeView, setActiveView] = useState<string>(statsViews[0] ?? 'DataFrame');
  const labelKey = symbol ?? 'stats';
  const items = [{
    key: labelKey,
    label: (
      <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
        <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>{labelKey}</span>
        <StatsViewSelect statsViews={statsViews} activeView={activeView} onChange={setActiveView} />
      </span>
    ),
    children: <StatsViewer dfSplit={dfSplit} activeView={activeView} maxHeight={maxHeight} />,
  }];
  return <Collapse defaultActiveKey={[labelKey]} items={items} style={style} />;
};

/** Hybrid fieldList Collapse: manages per-field activeStatsView state, shows StatsViewSelect in label for stats sub-fields. */
const HybridFieldListCollapse: React.FC<{
  data: Record<string, unknown>;
  viewSchema: Record<string, string>;
  tasks: TaskInfo[];
  threadId?: string;
  maxHeight: number;
  style?: React.CSSProperties;
}> = ({ data, viewSchema, tasks, threadId, maxHeight, style }) => {
  const [fieldActiveViews, setFieldActiveViews] = useState<Record<string, string>>({});

  const fieldStatsViews = useMemo(() => {
    const result: Record<string, string[]> = {};
    for (const [field, fieldViewType] of Object.entries(viewSchema)) {
      const d = data[field] as Record<string, unknown> | undefined;
      if (viewTypeToMode(fieldViewType) === 'mirror') {
        const taskId = d?.task_id as string | undefined;
        const task = taskId ? tasks.find(t => t.task_id === taskId) : undefined;
        const output = task?.output as Record<string, unknown> | undefined;
        if (Array.isArray(output?.stats_views)) { result[field] = output.stats_views as string[]; continue; }
      }
      if (Array.isArray(d?.stats_views)) result[field] = d.stats_views as string[];
    }
    return result;
  }, [data, viewSchema, tasks]);

  const items = Object.entries(viewSchema).map(([field, fieldViewType]) => {
    const statsViews = fieldStatsViews[field] ?? [];
    const activeView = fieldActiveViews[field] || statsViews[0];
    return {
      key: field,
      label: statsViews.length > 0 ? (
        <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
          <span>{field}</span>
          <StatsViewSelect
            statsViews={statsViews}
            activeView={activeView}
            onChange={(v) => setFieldActiveViews(prev => ({ ...prev, [field]: v }))}
          />
        </span>
      ) : field,
      children: (
        <FieldViewer
          fieldViewType={fieldViewType}
          fieldData={data[field]}
          tasks={tasks}
          threadId={threadId}
          maxHeight={maxHeight}
          activeStatsView={statsViews.length > 0 ? activeView : undefined}
        />
      ),
    };
  });

  return <Collapse defaultActiveKey={[]} items={items} style={style} />;
};

const DataViewer: React.FC<DataViewerProps> = ({
  mode,
  data,
  viewSchema,
  tasks = [],
  text,
  isLive,
  task,
  threadId,
  onViewData: _onViewData,
  onStreamEnd,
  maxHeight = 320,
  style,
  fieldList,
  activeStatsView,
}) => {
  if (fieldList) {
    type CollapseItem = { key: string; label: React.ReactNode; children: React.ReactNode };
    let items: CollapseItem[] = [];

    if (mode === 'mirror') {
      const taskId = (data as Record<string, unknown> | undefined)?.task_id as string | undefined;
      const resolvedTask = taskId ? tasks.find((t) => t.task_id === taskId) : task;
      if (resolvedTask) {
        return (
          <DataViewer
            mode={viewTypeToMode(resolvedTask.view_type)}
            data={resolvedTask.output}
            text={typeof (resolvedTask.output as Record<string, unknown> | undefined)?.answer === 'string'
              ? (resolvedTask.output as Record<string, unknown>).answer as string
              : undefined}
            isLive={resolvedTask.is_streaming && resolvedTask.status !== 'completed'}
            task={resolvedTask}
            tasks={tasks}
            threadId={threadId}
            maxHeight={maxHeight}
            style={style}
            fieldList
            activeStatsView={activeStatsView}
          />
        );
      }
    } else if (mode === 'hybrid' && viewSchema && data) {
      return (
        <HybridFieldListCollapse
          data={data as Record<string, unknown>}
          viewSchema={viewSchema as Record<string, string>}
          tasks={tasks}
          threadId={threadId}
          maxHeight={maxHeight}
          style={style}
        />
      );
    } else if (mode === 'json' && data && typeof data === 'object' && !Array.isArray(data)) {
      items = Object.entries(data as Record<string, unknown>).map(([key, val]) => ({
        key,
        label: key,
        children: <JsonViewer data={val} maxHeight={maxHeight} />,
      }));
    } else {
      // stream / markdown / dataframe / scalar — single collapsed panel
      const label = mode === 'stream' ? 'stream' : mode === 'markdown' ? 'content' : mode === 'dataframe' ? 'table' : 'value';
      // Stats dataframe: self-contained Collapse with Select in the panel label
      if (mode === 'dataframe') {
        const dataObj = data as Record<string, unknown> | undefined;
        const dfSplits = dataObj?.df_splits as StackCandleItem[] | undefined;
        const corrDfSplit = dataObj?.corr_df_split as DfSplit | undefined;
        const dfSplit = dataObj?.df_split as DfSplit | undefined;
        const statsViews = dataObj?.stats_views as string[] | undefined;
        // Unified view: df_splits (StackCandleStick) + corr_df_split (DataFrame) rendered together.
        if ((dfSplits?.length || corrDfSplit) && !statsViews?.length) {
          return (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {dfSplits?.length ? <StackCandleStickChart items={dfSplits} /> : null}
              {corrDfSplit ? <StatsDataFrame dfSplit={corrDfSplit} maxHeight={maxHeight} /> : null}
            </div>
          );
        }
        if (dfSplits?.length && statsViews?.includes('StackCandleStick')) {
          return <StackCandleStickChart items={dfSplits} />;
        }
        if (dfSplit && statsViews?.length) {
          return <StatsFieldListCollapse dfSplit={dfSplit} statsViews={statsViews} maxHeight={maxHeight ?? 320} style={style} symbol={dataObj?.symbol as string | undefined} />;
        }
      }
      const content = (() => {
        if (mode === 'stream') return <StreamViewer text={text} isLive={isLive} task={task} threadId={threadId} onViewData={_onViewData} onStreamEnd={onStreamEnd} maxHeight={maxHeight} style={style} />;
        if (mode === 'markdown') return <MarkdownViewer text={text} maxHeight={maxHeight} style={style} />;
        if (mode === 'dataframe') {
          const dataObj = data as Record<string, unknown> | undefined;
          const dfSplit = dataObj?.df_split as DfSplit | undefined;
          return dfSplit ? <StatsDataFrame dfSplit={dfSplit} maxHeight={maxHeight} /> : <JsonViewer data={data} maxHeight={maxHeight} style={style} />;
        }
        return <JsonViewer data={data} maxHeight={maxHeight} style={style} />;
      })();
      items = [{ key: label, label, children: content }];
    }

    if (items.length > 0) {
      return <Collapse defaultActiveKey={[]} items={items} style={style} />;
    }
  }

  if (mode === 'json') {
    return <JsonViewer data={data} maxHeight={maxHeight} style={style} />;
  }

  if (mode === 'webrequest') {
    return <WebRequestViewer data={data} maxHeight={maxHeight} style={style} />;
  }

  if (mode === 'markdown') {
    return <MarkdownViewer text={text} maxHeight={maxHeight} style={style} />;
  }

  if (mode === 'dataframe') {
    const dataObj = data as Record<string, unknown> | undefined;
    const dfSplits = dataObj?.df_splits as StackCandleItem[] | undefined;
    const dfSplit = dataObj?.df_split as DfSplit | undefined;
    const statsViews = dataObj?.stats_views as string[] | undefined;
    if (dfSplits?.length && statsViews?.includes('StackCandleStick')) {
      return <StackCandleStickChart items={dfSplits} />;
    }
    if (dfSplit && statsViews?.length) {
      return <StatsViewer dfSplit={dfSplit} activeView={activeStatsView ?? statsViews[0]} maxHeight={maxHeight} symbol={dataObj?.symbol as string | undefined} />;
    }
    return dfSplit
      ? <StatsDataFrame dfSplit={dfSplit} maxHeight={maxHeight} />
      : <JsonViewer data={data} maxHeight={maxHeight} style={style} />;
  }

  if (mode === 'mirror') {
    const taskId = (data as Record<string, unknown> | undefined)?.task_id as string | undefined;
    const resolvedTask = taskId ? tasks.find((t) => t.task_id === taskId) : task;
    if (!resolvedTask) {
      return <Text type="secondary">Mirror ref not resolved (task_id: {taskId ?? '—'})</Text>;
    }
    const taskMode = viewTypeToMode(resolvedTask.view_type);
    return (
      <DataViewer
        mode={taskMode}
        data={resolvedTask.output}
        text={typeof resolvedTask.output?.answer === 'string' ? resolvedTask.output.answer : undefined}
        isLive={resolvedTask.is_streaming && resolvedTask.status !== 'completed'}
        task={resolvedTask}
        tasks={tasks}
        threadId={threadId}
        onViewData={_onViewData}
        onStreamEnd={onStreamEnd}
        maxHeight={maxHeight}
        style={style}
        activeStatsView={activeStatsView}
      />
    );
  }

  if (mode === 'hybrid') {
    const outputData = data as Record<string, unknown> | undefined;
    const schema = viewSchema as Record<string, string> | undefined;
    if (!schema || !outputData) {
      return <JsonViewer data={data} maxHeight={maxHeight} style={style} />;
    }
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {Object.entries(schema).map(([field, fieldViewType]) => (
          <div key={field}>
            <Text type="secondary" style={{ fontSize: 11, marginBottom: 4, display: 'block' }}>
              {field}
            </Text>
            <FieldViewer
              fieldViewType={fieldViewType}
              fieldData={outputData[field]}
              tasks={tasks}
              threadId={threadId}
              maxHeight={maxHeight}
              style={style}
            />
          </div>
        ))}
      </div>
    );
  }

  return (
    <StreamViewer
      text={text}
      isLive={isLive}
      task={task}
      threadId={threadId}
      onStreamEnd={onStreamEnd}
      onViewData={_onViewData}
      maxHeight={maxHeight}
      style={style}
    />
  );
};

export default DataViewer;

