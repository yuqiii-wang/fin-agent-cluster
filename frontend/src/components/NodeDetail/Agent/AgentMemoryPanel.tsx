/**
 * AgentMemoryPanel — chronological list of agent memory entries.
 *
 * Each entry shows its type, seq_num, content summary, and action buttons:
 *  - Forget: marks the entry forgotten (excluded from future context).
 *  - Multi-select + Compact: select multiple entries and compact them into
 *    a single summary via a prompt dialog.
 *
 * Compacted/forgotten entries are hidden by default; a toggle shows them.
 */

import React, { useState } from 'react';
import {
  Button,
  Checkbox,
  Input,
  Modal,
  Space,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  CompressOutlined,
  DeleteOutlined,
  EyeInvisibleOutlined,
  EyeOutlined,
} from '@ant-design/icons';
import { STATUS_TAG_COLOR } from '../../../constants/statusColors';
import {
  COLOR_BORDER_BASE,
  COLOR_SURFACE_RAISED,
  COLOR_TEXT_SECONDARY,
} from '../../../constants/styleColors';
import type { MemoryEntry } from '../../../types';

const { Text } = Typography;
const { TextArea } = Input;

const ENTRY_TYPE_COLOR: Record<string, string> = {
  task_result: 'green',
  tool_call: 'blue',
  skill_applied: 'purple',
  reasoning: 'gold',
  compacted_summary: 'cyan',
};

function contentSummary(entry: MemoryEntry): string {
  const c = entry.content;
  if (entry.entry_type === 'reasoning') return String(c.text ?? '').slice(0, 120);
  if (entry.entry_type === 'tool_call') return `${c.name}(${JSON.stringify(c.args ?? {}).slice(0, 80)})`;
  if (entry.entry_type === 'task_result') return `${c.tool_name}: ${JSON.stringify(c.result ?? {}).slice(0, 100)}`;
  if (entry.entry_type === 'compacted_summary') return String(c.summary ?? '').slice(0, 120);
  return JSON.stringify(c).slice(0, 120);
}

/** Convert a memory entry to a markdown string for the data viewer. */
function contentMarkdown(entry: MemoryEntry): string {
  const c = entry.content;
  const typeLabel = entry.entry_type.replace(/_/g, ' ');
  const header = `**#${entry.seq_num} · ${typeLabel}**`;

  if (entry.entry_type === 'reasoning') {
    return `${header}\n\n${String(c.text ?? '')}`;
  }

  if (entry.entry_type === 'tool_call') {
    const args = JSON.stringify(c.args ?? {}, null, 2);
    return `${header}\n\n**Tool:** \`${c.name}\`\n\n**Arguments:**\n\`\`\`json\n${args}\n\`\`\``;
  }

  if (entry.entry_type === 'task_result') {
    const result = c.result as Record<string, unknown> | undefined ?? {};
    const lines: string[] = [`${header}\n\n**Task:** \`${c.tool_name}\``];
    const knownKeys = ['iteration', 'confirmed_peers', 'rejected_peers', 'corr_scores'];
    if (result.iteration !== undefined) lines.push(`\n**Iteration:** ${result.iteration}`);
    if (Array.isArray(result.confirmed_peers) && result.confirmed_peers.length > 0)
      lines.push(`\n**Confirmed peers:** ${(result.confirmed_peers as string[]).join(', ')}`);
    if (Array.isArray(result.rejected_peers) && result.rejected_peers.length > 0)
      lines.push(`\n**Rejected peers:** ${(result.rejected_peers as string[]).join(', ')}`);
    if (result.corr_scores && typeof result.corr_scores === 'object') {
      const rows = Object.entries(result.corr_scores as Record<string, number>)
        .map(([sym, v]) => `| ${sym} | ${typeof v === 'number' ? v.toFixed(4) : v} |`);
      if (rows.length > 0)
        lines.push(`\n\n| Symbol | Correlation |\n|--------|-------------|\n${rows.join('\n')}`);
    }
    // Any extra keys not already rendered
    const extras = Object.entries(result).filter(([k]) => !knownKeys.includes(k));
    if (extras.length > 0)
      lines.push(`\n\n\`\`\`json\n${JSON.stringify(Object.fromEntries(extras), null, 2)}\n\`\`\``);
    return lines.join('');
  }

  if (entry.entry_type === 'compacted_summary') {
    return `${header}\n\n${String(c.summary ?? '')}`;
  }

  if (entry.entry_type === 'skill_applied') {
    const parts = [`${header}`];
    if (c.summary) parts.push(`\n\n**Summary:** ${c.summary}`);
    if (c.instructions) parts.push(`\n\n**Instructions:**\n\n${c.instructions}`);
    return parts.join('');
  }

  return `${header}\n\n\`\`\`json\n${JSON.stringify(c, null, 2)}\n\`\`\``;
}

interface Props {
  memory: MemoryEntry[];
  nodeRunning: boolean;
  onForget: (memoryId: string) => Promise<void>;
  onCompact: (memoryIds: string[], summary: string) => Promise<void>;
  onViewData?: (label: string, data: string) => void;
}

const AgentMemoryPanel: React.FC<Props> = ({ memory, nodeRunning, onForget, onCompact, onViewData }) => {
  const [showAll, setShowAll] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [compactOpen, setCompactOpen] = useState(false);
  const [compactSummary, setCompactSummary] = useState('');
  const [compacting, setCompacting] = useState(false);
  const [forgettingId, setForgettingId] = useState<string | null>(null);

  const visible = showAll
    ? memory
    : memory.filter((m) => m.status === 'active');

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleForget = async (memoryId: string) => {
    setForgettingId(memoryId);
    try {
      await onForget(memoryId);
    } finally {
      setForgettingId(null);
    }
  };

  const handleCompact = async () => {
    if (selected.size < 2 || !compactSummary.trim()) return;
    setCompacting(true);
    try {
      await onCompact([...selected], compactSummary.trim());
      setSelected(new Set());
      setCompactSummary('');
      setCompactOpen(false);
    } finally {
      setCompacting(false);
    }
  };

  if (memory.length === 0) {
    return <Text type="secondary" style={{ fontSize: 12 }}>No memory entries yet.</Text>;
  }

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <Text strong style={{ fontSize: 12, color: COLOR_TEXT_SECONDARY }}>
          MEMORY ({visible.length}{showAll ? '' : ` / ${memory.length}`})
        </Text>
        <Button
          size="small"
          type="text"
          icon={showAll ? <EyeInvisibleOutlined /> : <EyeOutlined />}
          onClick={() => setShowAll((v) => !v)}
          style={{ fontSize: 11, color: COLOR_TEXT_SECONDARY }}
        >
          {showAll ? 'Active only' : 'Show all'}
        </Button>
        {selected.size >= 2 && (
          <Button
            size="small"
            icon={<CompressOutlined />}
            onClick={() => setCompactOpen(true)}
            style={{ marginLeft: 'auto' }}
          >
            Compact ({selected.size})
          </Button>
        )}
      </div>

      {visible.map((entry) => {
        const isActive = entry.status === 'active';
        const isSelected = selected.has(entry.memory_id);
        return (
          <div
            key={entry.memory_id}
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 8,
              padding: '5px 8px',
              marginBottom: 3,
              borderRadius: 4,
              borderLeft: `3px solid ${isActive ? '#1677ff33' : '#333'}`,
              background: isSelected ? COLOR_SURFACE_RAISED : 'transparent',
              opacity: isActive ? 1 : 0.45,
              cursor: onViewData ? 'pointer' : 'default',
            }}
            onClick={onViewData ? () => onViewData(`Memory #${entry.seq_num} · ${entry.entry_type.replace(/_/g, ' ')}`, contentMarkdown(entry)) : undefined}
          >
            {isActive && (
              <Checkbox
                checked={isSelected}
                onChange={() => toggleSelect(entry.memory_id)}
                style={{ marginTop: 2 }}
              />
            )}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                <Tag
                  color={ENTRY_TYPE_COLOR[entry.entry_type] ?? 'default'}
                  style={{ fontSize: 10, margin: 0 }}
                >
                  {entry.entry_type.replace('_', ' ')}
                </Tag>
                <Text style={{ fontSize: 10, color: COLOR_TEXT_SECONDARY }}>#{entry.seq_num}</Text>
                {entry.status !== 'active' && (
                  <Tag style={{ fontSize: 10, margin: 0 }}>{entry.status}</Tag>
                )}
              </div>
              <Text style={{ fontSize: 11 }}>{contentSummary(entry)}</Text>
            </div>
            {isActive && (
              <Tooltip title="Forget (excludes from future context)">
                <Button
                  size="small"
                  type="text"
                  danger
                  icon={<DeleteOutlined />}
                  loading={forgettingId === entry.memory_id}
                  onClick={() => handleForget(entry.memory_id)}
                  style={{ padding: '0 4px' }}
                />
              </Tooltip>
            )}
          </div>
        );
      })}

      <Modal
        open={compactOpen}
        title="Compact memory entries"
        okText="Compact"
        confirmLoading={compacting}
        onOk={handleCompact}
        onCancel={() => { setCompactOpen(false); setCompactSummary(''); }}
        okButtonProps={{ disabled: !compactSummary.trim() || selected.size < 2 }}
        destroyOnClose
      >
        <Space direction="vertical" style={{ width: '100%' }} size="small">
          <Text type="secondary" style={{ fontSize: 12 }}>
            Compacting {selected.size} entries. Enter a summary that will replace them.
            {nodeRunning && ' The agent will pause and restart with the new context.'}
          </Text>
          <TextArea
            rows={4}
            placeholder="Summary of the selected memory entries…"
            value={compactSummary}
            onChange={(e) => setCompactSummary(e.target.value)}
            autoFocus
          />
        </Space>
      </Modal>
    </>
  );
};

export default AgentMemoryPanel;
