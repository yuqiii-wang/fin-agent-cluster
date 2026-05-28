/**
 * AgentNodeDetail — full-panel detail view for NodeType.Agent nodes.
 *
 * Layout:
 *   Header  — node name, status tag, version, cancel button (same as NodeDetail)
 *   Tabs    — Tasks | Memory | Skills | Tools
 *     Tasks:        live tool-call executions with status; click to view output
 *     Memory:       chronological entries; per-entry forget; multi-select compact
 *     Skills:       active user skills; add new; forget existing
 *     Tools:        static tool registry (name, description, input schema)
 *
 * Loading: capabilities are fetched on mount and on a short polling interval
 * while the node is running so memory grows in real time.
 *
 * Pause/resume lifecycle:
 *   - Adding a skill or forgetting/compacting memory POSTs to the backend.
 *   - If the node is running the backend sets pause+auto_resume; the agent
 *     restarts with the new context automatically — no UI interaction needed.
 *   - A spinner overlay shows while the agent restarts (detected via node
 *     status transitioning from "paused" back to "running").
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Descriptions, Space, Spin, Tabs, Tag, Tooltip, Typography, message } from 'antd';
import { BranchesOutlined, ClearOutlined, RobotOutlined, StopOutlined } from '@ant-design/icons';
import { STATUS_HEX, STATUS_TAG_COLOR } from '../../../constants/statusColors';
import { isWorkActive, TERMINAL_WORK_STATUSES } from '../../../constants/lifecycleStatus';
import { COLOR_SURFACE_RAISED, COLOR_TEXT_SECONDARY } from '../../../constants/styleColors';
import {
  addAgentSkill,
  compactAgentMemory,
  forgetAgentMemory,
  forgetAgentSkill,
  getAgentCapabilities,
  getAgentStepStates,
  invalidateNodeCache,
  fetchNodeSkills,
} from '../../../api/threads';
import AgentCapabilitiesPanel from './AgentCapabilitiesPanel';
import AgentMemoryPanel from './AgentMemoryPanel';
import AgentSkillsPanel from './AgentSkillsPanel';
import AgentStepStatePanel from './AgentStepStatePanel';
import TaskDetail from '../TaskDetail';
import { viewTypeToMode } from '../../DataViewer/index';

import type { AgentCapabilities, NodeInfo, NodeSkillFile, StepStateEntry, TaskInfo, TaskRunEntry } from '../../../types';
import type { DataViewerMode } from '../../DataViewer/index';

const { Title, Text } = Typography;

const POLL_INTERVAL_MS = 4000;

interface Props {
  node: NodeInfo;
  tasks?: TaskInfo[];
  threadId: string;
  tokenStreams?: Record<string, string>;
  threadActive?: boolean;
  activeVersion?: number;
  onViewData?: (label: string, data: unknown, opts?: { mode?: DataViewerMode; viewSchema?: Record<string, string>; fieldList?: boolean; nodeContext?: 'input' | 'output'; taskId?: string; activeStatsView?: string }) => void;
  onCancelNode?: (nodeId: string) => void;
  onCancelTask?: (taskId: string, nodeId?: string) => void;
  cancellingId?: string | null;
  onReExplore?: (node: NodeInfo) => void;
  /** Accumulated SSE task run log filtered to this node. */
  taskRunLog?: TaskRunEntry[];
}

type View = { type: 'node' } | { type: 'task'; taskId: string };

const AgentNodeDetail: React.FC<Props> = ({
  node,
  tasks = [],
  threadId,
  tokenStreams = {},
  threadActive = false,
  activeVersion,
  onViewData,
  onCancelNode,
  onCancelTask,
  cancellingId,
  onReExplore,
  taskRunLog = [],
}) => {
  const [caps, setCaps] = useState<AgentCapabilities | null>(null);
  const [stepStates, setStepStates] = useState<StepStateEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [nodeSkillFiles, setNodeSkillFiles] = useState<NodeSkillFile[]>([]);
  const [activeTab, setActiveTab] = useState('tasks');
  const [isHeaderHovered, setIsHeaderHovered] = useState(false);
  const [hoveredTaskId, setHoveredTaskId] = useState<string | null>(null);
  const [view, setView] = useState<View>({ type: 'node' });
  const [invalidatingCache, setInvalidatingCache] = useState(false);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchCaps = useCallback(async () => {
    try {
      const data = await getAgentCapabilities(threadId, node.node_id);
      setCaps(data);
    } catch {
      // non-fatal; node may not be running yet
    } finally {
      setLoading(false);
    }
  }, [threadId, node.node_id]);

  const fetchStepStates = useCallback(async () => {
    try {
      const data = await getAgentStepStates(threadId, node.node_id);
      setStepStates(data.iterations);
    } catch {
      // non-fatal; no step state yet for this node
    }
  }, [threadId, node.node_id]);

  // Poll while node is active; single fetch otherwise.
  useEffect(() => {
    fetchCaps();
    fetchStepStates();
    if (isWorkActive(node.status)) {
      pollRef.current = setInterval(() => {
        fetchCaps();
        fetchStepStates();
      }, POLL_INTERVAL_MS);
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [fetchCaps, fetchStepStates, node.status]);

  // Fetch static built-in skills files for this node (keyed on node_name).
  useEffect(() => {
    fetchNodeSkills().then((all) => {
      const entry = all.find((r) => r.node_name === node.node_name);
      setNodeSkillFiles(entry?.skills ?? []);
    }).catch(() => {/* non-fatal */});
  }, [node.node_name]);

  // Reset to node view when the displayed node changes.
  useEffect(() => {
    setView({ type: 'node' });
  }, [node.node_id]);

  const handleAddSkill = async (summary: string, instructions: string) => {
    try {
      await addAgentSkill(threadId, node.node_id, summary, instructions);
      await fetchCaps();
      if (isWorkActive(node.status)) {
        message.info('Skill added — agent will pause and restart with the new context.');
      }
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleForgetSkill = async (skillId: string) => {
    try {
      await forgetAgentSkill(threadId, node.node_id, skillId);
      await fetchCaps();
      if (isWorkActive(node.status)) {
        message.info('Skill removed — agent will pause and restart without it.');
      }
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleForgetMemory = async (memoryId: string) => {
    try {
      await forgetAgentMemory(threadId, node.node_id, memoryId);
      await fetchCaps();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleCompactMemory = async (memoryIds: string[], summary: string) => {
    try {
      await compactAgentMemory(threadId, node.node_id, memoryIds, summary);
      await fetchCaps();
      if (isWorkActive(node.status)) {
        message.info('Memory compacted — agent will pause and restart with the compacted context.');
      }
    } catch (err) {
      message.error(String(err));
    }
  };

  const nodeVersion = node.version ?? 0;
  const isShared = activeVersion !== undefined && nodeVersion < activeVersion;
  const isInnerNode = !!node.parent_node_id;
  const canReExplore = !isInnerNode && !!onReExplore && (
    TERMINAL_WORK_STATUSES.has(node.status as never) || isWorkActive(node.status)
  );
  const nodeRunning = node.status === 'running';

  // ── Task overlay ──────────────────────────────────────────────────────────
  if (view.type === 'task') {
    const task = tasks.find((t) => t.task_id === view.taskId);
    return (
      <div>
        <Button
          size="small"
          type="text"
          onClick={() => setView({ type: 'node' })}
          style={{ marginBottom: 12, padding: '0 4px', color: COLOR_TEXT_SECONDARY }}
        >
          ← Back
        </Button>
        {task ? (
          <TaskDetail
            key={task.task_id}
            task={task}
            nodeStatus={node.status}
            threadId={threadId}
            liveStream={tokenStreams[task.task_id]}
            onViewData={onViewData}
            onCancelTask={onCancelTask}
            cancellingId={cancellingId}
          />
        ) : (
          <Text type="secondary">Task not found.</Text>
        )}
      </div>
    );
  }

  return (
    <div>
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div
        style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}
        onMouseEnter={() => setIsHeaderHovered(true)}
        onMouseLeave={() => setIsHeaderHovered(false)}
      >
        <RobotOutlined style={{ fontSize: 14 }} />
        <Title level={5} style={{ margin: 0 }}>{node.node_name}</Title>
        <Tag color={STATUS_TAG_COLOR[node.status] ?? 'default'}>{node.status}</Tag>
        <Tag color="purple">Agent</Tag>
        <Tooltip title={isShared ? `shared from v${nodeVersion}` : undefined}>
          <Tag
            color={isShared ? 'default' : nodeVersion > 0 ? 'blue' : undefined}
            style={{ cursor: isShared ? 'help' : 'default' }}
          >
            v{nodeVersion}{isShared ? ' (shared)' : ''}
          </Tag>
        </Tooltip>
        {isWorkActive(node.status) && onCancelNode && isHeaderHovered && (
          <Button
            size="small"
            danger
            icon={<StopOutlined />}
            loading={cancellingId === node.node_id}
            onClick={() => onCancelNode(node.node_id)}
            style={{ marginLeft: 'auto' }}
          />
        )}
        {canReExplore && (
          <Tooltip title={
            isWorkActive(node.status) && threadActive
              ? 'Node must finish before re-exploring'
              : 'Fork graph from this node'
          }>
            <Button
              size="small"
              icon={<BranchesOutlined />}
              disabled={isWorkActive(node.status) && threadActive}
              onClick={() => !(isWorkActive(node.status) && threadActive) && onReExplore!(node)}
              style={{ marginLeft: 'auto' }}
            >
              Re-explore
            </Button>
          </Tooltip>
        )}
        {node.status === 'completed' && tasks.length > 0 && (
          <Tooltip title="Zero out task cache TTLs so tasks re-run on the next execution">
            <Button
              size="small"
              icon={<ClearOutlined />}
              loading={invalidatingCache}
              onClick={async () => {
                setInvalidatingCache(true);
                try {
                  const { invalidated } = await invalidateNodeCache(threadId, node.node_id);
                  message.success(`Cache invalidated for ${invalidated} task(s)`);
                } catch {
                  message.error('Failed to invalidate cache');
                } finally {
                  setInvalidatingCache(false);
                }
              }}
            >
              Invalidate Cache
            </Button>
          </Tooltip>
        )}
      </div>

      <Descriptions size="small" column={1} bordered style={{ marginBottom: 12 }}>
        <Descriptions.Item label="Node ID">
          <Text copyable code style={{ fontSize: 11 }}>{node.node_id}</Text>
        </Descriptions.Item>
      </Descriptions>

      {/* ── Input / Output ─────────────────────────────────────────── */}
      {(node.input || node.output || taskRunLog.length > 0) && (
        <Space size="small" style={{ marginBottom: 12 }}>
          {node.input && (
            <Button
              size="small"
              onClick={() => onViewData?.(`${node.node_name} · Input`, node.input, { nodeContext: 'input' })}
            >
              Input
            </Button>
          )}
          {(node.output || taskRunLog.length > 0) && (
            <Button
              size="small"
              onClick={() => onViewData?.(`${node.node_name} · Output`, node.output, {
                mode: node.output ? viewTypeToMode(node.view_type) : undefined,
                viewSchema: node.view_schema as Record<string, string> | undefined,
                fieldList: !!node.output,
                nodeContext: 'output',
                nodeId: node.node_id,
              })}
            >
              Output
            </Button>
          )}
        </Space>
      )}

      {/* ── Tabs (completed output) ────────────────────────────────────── */}
      <Spin spinning={loading} size="small">
        <Tabs
          size="small"
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: 'tasks',
              label: `Tasks (${tasks.length})`,
              children: tasks.length === 0 ? (
                <Text type="secondary" style={{ fontSize: 12 }}>No tasks running yet.</Text>
              ) : (
                <>
                  {tasks.map((t) => {
                    const tagStatus = t.status === 'paused' && node.status === 'completed' ? 'completed' : t.status;
                    return (
                      <div
                        key={t.task_id}
                        style={{
                          cursor: 'pointer',
                          borderRadius: 4,
                          padding: '6px 10px',
                          marginBottom: 3,
                          borderLeft: `3px solid ${STATUS_HEX[t.status] ?? '#8c8c8c'}`,
                          background: hoveredTaskId === t.task_id ? COLOR_SURFACE_RAISED : 'transparent',
                          transition: 'background 0.15s',
                        }}
                        onClick={() => {
                          setView({ type: 'task', taskId: t.task_id });
                          if (t.output) {
                            onViewData?.(`${t.task_name} · Output`, t.output, {
                              mode: viewTypeToMode(t.view_type),
                            });
                          }
                        }}
                        onMouseEnter={() => setHoveredTaskId(t.task_id)}
                        onMouseLeave={() => setHoveredTaskId(null)}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <Text style={{ flex: 1, fontSize: 12 }}>{t.task_name}</Text>
                          <Tag color={STATUS_TAG_COLOR[tagStatus] ?? 'default'} style={{ fontSize: 10 }}>
                            {tagStatus}
                          </Tag>
                          {hoveredTaskId === t.task_id && isWorkActive(t.status) && onCancelTask && (
                            <Button
                              size="small"
                              danger
                              icon={<StopOutlined />}
                              loading={cancellingId === t.task_id}
                              onClick={(e) => { e.stopPropagation(); onCancelTask(t.task_id, t.node_id); }}
                            >
                              Cancel
                            </Button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </>
              ),
            },
            {
              key: 'memory',
              label: `Memory${caps ? ` (${caps.memory.filter((m) => m.status === 'active').length})` : ''}`,
              children: caps ? (
                <AgentMemoryPanel
                  memory={caps.memory}
                  nodeRunning={nodeRunning}
                  onForget={handleForgetMemory}
                  onCompact={handleCompactMemory}
                  onViewData={onViewData ? (label, data) => onViewData(label, data) : undefined}
                />
              ) : null,
            },
            {
              key: 'skills',
              label: `Skills${caps ? ` (${nodeSkillFiles.length + caps.skills.filter((s) => s.status === 'active').length})` : ''}`,
              children: caps ? (
                <AgentSkillsPanel
                  skills={caps.skills}
                  nodeSkillFiles={nodeSkillFiles}
                  nodeRunning={nodeRunning}
                  tools={caps.tools}
                  onAdd={handleAddSkill}
                  onForget={handleForgetSkill}
                />
              ) : null,
            },
            {
              key: 'tools',
              label: `Tools${caps ? ` (${caps.tools.length})` : ''}`,
              children: caps ? (
                <AgentCapabilitiesPanel tools={caps.tools} />
              ) : null,
            },
          ]}
        />
      </Spin>
    </div>
  );
};

export default AgentNodeDetail;

