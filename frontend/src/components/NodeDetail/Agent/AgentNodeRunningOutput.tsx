/**
 * AgentNodeRunningOutput — live running task log for an agent node.
 *
 * Accumulates task run entries pushed from SSE task_status events.
 * Entries are never removed — re-runs appear as additional rows below
 * completed ones.  Click a row to expand its input / output inline.
 *
 * llm_orchestration tasks running show a special "Thinking / Judgement"
 * label with an animated indicator.
 */

import React, { useState } from 'react';
import { LoadingOutlined, RightOutlined } from '@ant-design/icons';
import { Tag, Typography } from 'antd';
import { STATUS_HEX, STATUS_TAG_COLOR } from '../../../constants/statusColors';
import {
  COLOR_BORDER_SUBTLE,
  COLOR_SURFACE_RAISED,
  COLOR_TEXT_SECONDARY,
} from '../../../constants/styleColors';
import type { TaskRunEntry } from '../../../types';

const { Text } = Typography;

interface Props {
  entries: TaskRunEntry[];
  /** Live LLM token streams keyed by task_id. */
  tokenStreams?: Record<string, string>;
  showTitle?: boolean;
}

/** Compact JSON block for task input / output. */
const JsonBlock: React.FC<{ data: Record<string, unknown> }> = ({ data }) => (
  <pre
    style={{
      margin: 0,
      padding: '6px 8px',
      fontSize: 11,
      lineHeight: 1.4,
      background: COLOR_SURFACE_RAISED,
      border: `1px solid ${COLOR_BORDER_SUBTLE}`,
      borderRadius: 4,
      overflowX: 'auto',
      whiteSpace: 'pre-wrap',
      wordBreak: 'break-word',
      color: '#d9d9d9',
      maxHeight: 240,
      overflowY: 'auto',
    }}
  >
    {JSON.stringify(data, null, 2)}
  </pre>
);

const AgentNodeRunningOutput: React.FC<Props> = ({ entries, tokenStreams = {}, showTitle = true }) => {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  if (entries.length === 0) return null;

  const toggle = (id: string) =>
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div style={{ marginBottom: 12 }}>
      {showTitle && (
        <Text
          style={{
            fontSize: 10,
            textTransform: 'uppercase',
            letterSpacing: 1,
            color: COLOR_TEXT_SECONDARY,
            display: 'block',
            marginBottom: 4,
          }}
        >
          Running Output
        </Text>
      )}

      {[...entries].reverse().map((entry) => {
        const isOrch = entry.task_name === 'llm_orchestration';
        const isRunning = entry.status === 'running';
        const isExpanded = expandedIds.has(entry.task_id);
        const liveStream = tokenStreams[entry.task_id];

        const displayLabel =
          isOrch && isRunning ? 'Thinking / Judgement' : entry.task_name;
        const borderColor = STATUS_HEX[entry.status] ?? '#8c8c8c';

        return (
          <div
            key={entry.task_id}
            style={{
              borderLeft: `3px solid ${borderColor}`,
              borderRadius: 4,
              marginBottom: 3,
              background: 'transparent',
              overflow: 'hidden',
            }}
          >
            {/* Row header — click to expand */}
            <div
              role="button"
              tabIndex={0}
              onClick={() => toggle(entry.task_id)}
              onKeyDown={(e) => e.key === 'Enter' && toggle(entry.task_id)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '5px 8px',
                cursor: 'pointer',
                userSelect: 'none',
              }}
            >
              <RightOutlined
                style={{
                  fontSize: 9,
                  color: COLOR_TEXT_SECONDARY,
                  transition: 'transform 0.15s',
                  transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)',
                  flexShrink: 0,
                }}
              />
              {isOrch && isRunning && (
                <LoadingOutlined style={{ fontSize: 11, color: '#faad14', flexShrink: 0 }} />
              )}
              <Text style={{ flex: 1, fontSize: 12 }}>{displayLabel}</Text>
              <Tag
                color={STATUS_TAG_COLOR[entry.status] ?? 'default'}
                style={{ fontSize: 10, margin: 0 }}
              >
                {entry.status}
              </Tag>
            </div>

            {/* Expanded content */}
            {isExpanded && (
              <div style={{ padding: '0 8px 8px 20px' }}>
                {/* Live stream for running streaming tasks */}
                {isRunning && liveStream && (
                  <div style={{ marginBottom: 6 }}>
                    <Text
                      style={{
                        fontSize: 10,
                        color: COLOR_TEXT_SECONDARY,
                        display: 'block',
                        marginBottom: 2,
                      }}
                    >
                      Stream
                    </Text>
                    <pre
                      style={{
                        margin: 0,
                        padding: '6px 8px',
                        fontSize: 11,
                        lineHeight: 1.4,
                        background: COLOR_SURFACE_RAISED,
                        border: `1px solid ${COLOR_BORDER_SUBTLE}`,
                        borderRadius: 4,
                        overflowX: 'auto',
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        color: '#d9d9d9',
                        maxHeight: 200,
                        overflowY: 'auto',
                      }}
                    >
                      {liveStream}
                    </pre>
                  </div>
                )}

                {/* Output (completed/failed) */}
                {entry.output && (
                  <div style={{ marginBottom: 6 }}>
                    <Text
                      style={{
                        fontSize: 10,
                        color: COLOR_TEXT_SECONDARY,
                        display: 'block',
                        marginBottom: 2,
                      }}
                    >
                      Output
                    </Text>
                    <JsonBlock data={entry.output} />
                  </div>
                )}

                {/* Input (always show when no output yet or on expansion) */}
                {entry.input && !entry.output && (
                  <div>
                    <Text
                      style={{
                        fontSize: 10,
                        color: COLOR_TEXT_SECONDARY,
                        display: 'block',
                        marginBottom: 2,
                      }}
                    >
                      Input
                    </Text>
                    <JsonBlock data={entry.input} />
                  </div>
                )}

                {isRunning && !liveStream && !entry.output && !entry.input && (
                  <Text style={{ fontSize: 11, color: COLOR_TEXT_SECONDARY }}>
                    Running…
                  </Text>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};

export default AgentNodeRunningOutput;
