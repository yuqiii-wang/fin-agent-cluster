/**
 * StreamViewer — LLM token stream display.
 *
 * - While live: renders accumulated tokens as a styled "Thinking…" block.
 * - On completion: shows a collapsible Thinking panel (if present); answer
 *   is accessed via ``onViewData`` in the parent (TaskDetail).
 */

import React, { useEffect, useRef, useState } from 'react';
import { Collapse, Typography } from 'antd';
import type { CollapseProps } from 'antd';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useTokenStream } from '../../hooks/useTokenStream';
import {
  COLOR_BORDER_BASE, COLOR_BORDER_SUBTLE, COLOR_BRAND_BLUE,
  COLOR_SURFACE_BASE, COLOR_TEXT_MUTED, COLOR_TEXT_SECONDARY,
} from '../../constants/styleColors';
import type { TaskInfo } from '../../types';

const { Text } = Typography;

const mdBoxBase: React.CSSProperties = {
  background: COLOR_SURFACE_BASE,
  borderRadius: 6,
  padding: '10px 14px',
  border: `1px solid ${COLOR_BORDER_BASE}`,
};

export interface StreamViewerProps {
  /** Pre-assembled or forwarded live text from the thread-level subscription. */
  text?: string;
  /** True while the stream is still in progress — shows a blinking cursor. */
  isLive?: boolean;
  /** Task context — enables per-task subscription fallback. */
  task?: TaskInfo;
  /** Thread ID for the per-task subscription fallback. */
  threadId?: string;
  /** Called once when the stream finishes (either path). */
  onStreamEnd?: () => void;
  /**
   * When provided the completed output area becomes clickable: clicking it
   * calls this callback with a combined thinking + answer markdown string,
   * overwriting whatever is currently shown in the parent DataViewer panel.
   */
  onViewData?: (label: string, data: unknown) => void;
  maxHeight?: number;
  style?: React.CSSProperties;
}

const StreamViewer: React.FC<StreamViewerProps> = ({
  text: textProp,
  isLive = false,
  task,
  threadId,
  onStreamEnd,
  onViewData,
  maxHeight = 320,
  style,
}) => {
  const isStreamTask = !!task?.is_streaming;
  const isTaskRunning = task?.status === 'running';

  const shouldSubscribe =
    isStreamTask &&
    isTaskRunning &&
    textProp === undefined &&
    !!threadId;

  const [localTokens, setLocalTokens] = useState<string[]>([]);
  const [localDone, setLocalDone] = useState(false);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  // Reset on task_id change (different task selected).
  useEffect(() => {
    setLocalTokens([]);
    setLocalDone(false);
  }, [task?.task_id]);

  // Clear accumulated tokens when task goes back to 'running' (retry triggered).
  const prevStatusRef = useRef<string | undefined>(task?.status);
  useEffect(() => {
    if (task?.status === 'running' && prevStatusRef.current !== undefined && prevStatusRef.current !== 'running') {
      setLocalTokens([]);
      setLocalDone(false);
    }
    prevStatusRef.current = task?.status;
  }, [task?.status]);

  useTokenStream({
    threadId: threadId ?? '',
    taskId: shouldSubscribe && task ? task.task_id : null,
    active: shouldSubscribe,
    onToken: (token) => setLocalTokens((prev) => [...prev, token]),
    onEnd: () => setLocalDone(true),
  });

  // Notify parent when stream ends via the shouldSubscribe path.
  useEffect(() => {
    if (localDone) onStreamEnd?.();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [localDone]);

  // Notify parent when stream ends via the thread-level (textProp) path.
  const prevIsLiveRef = useRef(isLive);
  useEffect(() => {
    if (prevIsLiveRef.current && !isLive && !shouldSubscribe) {
      onStreamEnd?.();
    }
    prevIsLiveRef.current = isLive;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLive]);

  useEffect(() => {
    const el = scrollContainerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [localTokens.length]);

  const live = isLive || (shouldSubscribe && !localDone);

  if (live) {
    const liveText = textProp !== undefined ? textProp : localTokens.join('');
    return (
      <div style={style}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
          <Text style={{ fontSize: 11, color: COLOR_TEXT_SECONDARY, fontStyle: 'italic' }}>Thinking…</Text>
          <span
            style={{
              display: 'inline-block',
              width: 7,
              height: 7,
              borderRadius: '50%',
              background: COLOR_BRAND_BLUE,
              animation: 'blink 1s step-end infinite',
            }}
          />
        </div>
        <div
          ref={scrollContainerRef}
          style={{
            ...mdBoxBase,
            maxHeight,
            overflowY: 'auto',
            color: COLOR_TEXT_MUTED,
            fontSize: 12,
            fontStyle: 'italic',
            borderColor: COLOR_BORDER_SUBTLE,
          }}
        >
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{liveText}</ReactMarkdown>
        </div>
      </div>
    );
  }

  // Completed stream — read thinking from task.output (backend-extracted).
  // Fall back to locally accumulated tokens when task was cancelled mid-stream (no stored output).
  const thinking = (task?.output?.thinking as string | undefined)
    ?? (localTokens.length > 0 ? localTokens.join('') : undefined);
  const answerRaw = task?.output?.answer;
  const answer = answerRaw !== undefined && answerRaw !== null ? answerRaw : undefined;

  const handleOutputClick = onViewData
    ? () => {
        const parts: string[] = [];
        if (thinking) parts.push(`### Thinking\n\n${thinking}`);
        if (answer !== undefined) {
          const answerText = typeof answer === 'string'
            ? answer
            : '```json\n' + JSON.stringify(answer, null, 2) + '\n```';
          parts.push(`### Answer\n\n${answerText}`);
        }
        onViewData(`${task?.task_name ?? 'stream'} · Output`, parts.join('\n\n---\n\n') || '(no output)');
      }
    : undefined;

  const thinkItems: CollapseProps['items'] | undefined = thinking
    ? [
        {
          key: 'thinking',
          label: <Text style={{ fontSize: 11, color: COLOR_TEXT_SECONDARY }}>Thinking</Text>,
          children: (
            <div
              style={{
                color: COLOR_TEXT_SECONDARY,
                fontSize: 11,
                maxHeight: 200,
                overflowY: 'auto',
              }}
            >
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{thinking}</ReactMarkdown>
            </div>
          ),
        },
      ]
    : undefined;

  return (
    <div
      style={{ ...style, cursor: handleOutputClick ? 'pointer' : undefined }}
      onClick={handleOutputClick}
      title={handleOutputClick ? 'Click to view full output' : undefined}
    >
      {thinkItems ? (
        <Collapse ghost size="small" items={thinkItems} />
      ) : (
        <Text style={{ fontSize: 11, color: COLOR_TEXT_MUTED, fontStyle: 'italic' }}>
          (no thinking captured)
        </Text>
      )}
    </div>
  );
};

export default StreamViewer;
