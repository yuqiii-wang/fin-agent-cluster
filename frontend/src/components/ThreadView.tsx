/**
 * ThreadView — full thread detail panel.
 *
 * Layout (top-to-bottom):
 *  1. Thread status bar
 *  2. Node graph + node detail side panel (Splitter)
 *  3. Node timeline
 *  4. Task Gantt
 */

import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Badge, Card, Divider, Splitter, Spin, Tag, Typography } from 'antd';
import NodeGraph from './NodeGraph';
import NodeDetail from './NodeDetail';
import NodeTimeline from './NodeTimeline';
import TaskGantt from './TaskGantt';
import { useCentrifugoSse } from '../hooks/useCentrifugoSse';
import { useCentrifugoLlm } from '../hooks/useCentrifugoLlm';
import { useThreadData } from '../hooks/useThreadData';
import type { SseEvent, SseInfo } from '../types';

const { Title, Text } = Typography;

const STATUS_BADGE: Record<string, 'processing' | 'success' | 'error' | 'warning' | 'default'> = {
  received:  'processing',
  running:   'processing',
  completed: 'success',
  failed:    'error',
  cancelled: 'warning',
};

const TERMINAL = new Set(['completed', 'failed', 'cancelled']);

interface Props {
  threadId: string;
  sseInfo: SseInfo | null;
  llmInfo: SseInfo | null;
}

const ThreadView: React.FC<Props> = ({ threadId, sseInfo, llmInfo }) => {
  const { thread, nodes, tasks, refresh } = useThreadData(threadId);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [tokenStreams, setTokenStreams] = useState<Record<string, string>>({});

  const isDone = TERMINAL.has(thread?.status ?? '');

  // Reset accumulated token streams whenever we switch to a different thread.
  useEffect(() => { setTokenStreams({}); }, [threadId]);

  const handleSseEvent = useCallback(
    (ev: SseEvent) => {
      // Trigger a data refresh on any lifecycle event.
      if (
        ev.event === 'node_status' ||
        ev.event === 'task_status' ||
        ev.event === 'done' ||
        ev.event === 'stream_complete' ||
        ev.event === 'query_status'
      ) {
        refresh();
      }
    },
    [refresh],
  );

  const handleToken = useCallback(
    (taskId: string, token: string, _seq: number) => {
      setTokenStreams((prev) => ({ ...prev, [taskId]: (prev[taskId] ?? '') + token }));
    },
    [],
  );

  useCentrifugoSse({ sseInfo, onEvent: handleSseEvent, done: isDone });
  useCentrifugoLlm({ llmInfo, onToken: handleToken, done: isDone });

  const selectedNode = nodes.find((n) => n.node_id === selectedNodeId) ?? null;

  if (!thread) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
        <Spin />
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Status bar */}
      <Card size="small" style={{ borderRadius: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <Badge status={STATUS_BADGE[thread.status] ?? 'default'} text={thread.status.toUpperCase()} />
          <Text type="secondary" style={{ fontSize: 12 }}>{thread.query}</Text>
          <Text copyable code style={{ fontSize: 10, color: '#595959' }}>{thread.thread_id}</Text>
        </div>
        {thread.error && (
          <Alert title={thread.error} type="error" showIcon style={{ marginTop: 8 }} />
        )}
      </Card>

      {/* Node graph + detail panel */}
      <Card
        size="small"
        title={<Text strong>Node Graph</Text>}
        style={{ borderRadius: 8 }}
        styles={{ body: { padding: 0 } }}
      >
        <Splitter style={{ height: 380 }}>
          <Splitter.Panel defaultSize="60%" min="40%">
            <div style={{ padding: '8px 0' }}>
              <NodeGraph
                nodes={nodes}
                selectedNodeId={selectedNodeId}
                onSelectNode={(id) => setSelectedNodeId(id === selectedNodeId ? null : id)}
              />
            </div>
          </Splitter.Panel>
          <Splitter.Panel>
            <div
              style={{
                padding: 16,
                overflowY: 'auto',
                height: '100%',
                borderLeft: '1px solid #1f1f1f',
              }}
            >
              {selectedNode ? (
                <NodeDetail node={selectedNode} tasks={tasks} threadId={threadId} tokenStreams={tokenStreams} />
              ) : (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  Click a node to see its details.
                </Text>
              )}
            </div>
          </Splitter.Panel>
        </Splitter>
      </Card>

      {/* Timeline */}
      <Card
        size="small"
        title={<Text strong>Node Timeline</Text>}
        style={{ borderRadius: 8 }}
      >
        <NodeTimeline
          nodes={nodes}
          selectedNodeId={selectedNodeId}
          onSelectNode={(id) => setSelectedNodeId(id === selectedNodeId ? null : id)}
        />
      </Card>

      {/* Gantt */}
      <Card
        size="small"
        title={<Text strong>Task Gantt</Text>}
        style={{ borderRadius: 8 }}
      >
        <TaskGantt tasks={tasks} />
      </Card>

      {/* Completed answer */}
      {thread.answer && (
        <Card
          size="small"
          title={<Text strong>Answer</Text>}
          style={{ borderRadius: 8 }}
        >
          <pre
            style={{
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              margin: 0,
              color: '#d9d9d9',
              fontSize: 13,
            }}
          >
            {thread.answer}
          </pre>
        </Card>
      )}
    </div>
  );
};

export default ThreadView;
