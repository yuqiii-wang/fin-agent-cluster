/**
 * AgentStepStatePanel — shows per-iteration global_state and step_state snapshots.
 *
 * Each iteration is an expandable card.  Inside each card two collapsible
 * sections show the JSON for global_state and step_state respectively.
 * Clicking a field value opens the parent onViewData viewer when provided.
 */

import React, { useState } from 'react';
import { Collapse, Empty, Tag, Typography } from 'antd';
import { GlobalOutlined, NodeIndexOutlined } from '@ant-design/icons';
import { COLOR_BORDER_BASE, COLOR_TEXT_SECONDARY } from '../../../constants/styleColors';
import type { StepStateEntry } from '../../../types';

const { Text } = Typography;

/** Render a plain JSON value as a compact monospace string. */
function jsonLine(val: unknown): string {
  if (val === null || val === undefined) return 'null';
  if (typeof val === 'object') return JSON.stringify(val);
  return String(val);
}

interface JsonFieldsProps {
  data: Record<string, unknown>;
  onViewData?: (label: string, data: string) => void;
  prefix: string;
}

const JsonFields: React.FC<JsonFieldsProps> = ({ data, onViewData, prefix }) => {
  const entries = Object.entries(data);
  if (entries.length === 0) {
    return <Text type="secondary" style={{ fontSize: 11 }}>—</Text>;
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      {entries.map(([key, val]) => {
        const isObject = val !== null && typeof val === 'object';
        const display = jsonLine(val);
        const truncated = display.length > 140 ? display.slice(0, 140) + '…' : display;
        return (
          <div
            key={key}
            style={{
              display: 'flex',
              gap: 8,
              alignItems: 'baseline',
              cursor: isObject && onViewData ? 'pointer' : 'default',
            }}
            onClick={
              isObject && onViewData
                ? () =>
                    onViewData(
                      `${prefix} · ${key}`,
                      `\`\`\`json\n${JSON.stringify(val, null, 2)}\n\`\`\``,
                    )
                : undefined
            }
          >
            <Text
              style={{
                fontSize: 11,
                color: COLOR_TEXT_SECONDARY,
                flexShrink: 0,
                minWidth: 120,
                fontFamily: 'monospace',
              }}
            >
              {key}
            </Text>
            <Text
              style={{
                fontSize: 11,
                fontFamily: 'monospace',
                color: isObject && onViewData ? '#1677ff' : undefined,
                textDecoration: isObject && onViewData ? 'underline dotted' : undefined,
                wordBreak: 'break-all',
              }}
            >
              {truncated}
            </Text>
          </div>
        );
      })}
    </div>
  );
};

interface Props {
  iterations: StepStateEntry[];
  onViewData?: (label: string, data: string) => void;
}

const AgentStepStatePanel: React.FC<Props> = ({ iterations, onViewData }) => {
  const [openKeys, setOpenKeys] = useState<string[]>(
    iterations.length > 0 ? [`iter-${iterations[iterations.length - 1].iteration}`] : [],
  );

  if (iterations.length === 0) {
    return <Empty description="No step state snapshots yet." imageStyle={{ height: 40 }} />;
  }

  return (
    <Collapse
      activeKey={openKeys}
      onChange={(keys) => setOpenKeys(Array.isArray(keys) ? keys : [keys])}
      size="small"
      style={{ background: 'transparent', border: `1px solid ${COLOR_BORDER_BASE}` }}
      items={iterations.map((entry) => {
        const iterKey = `iter-${entry.iteration}`;
        const hasStepState = Object.keys(entry.step_state).length > 0;
        return {
          key: iterKey,
          label: (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Tag color="blue" style={{ fontSize: 10, margin: 0 }}>
                iter {entry.iteration}
              </Tag>
              <Text style={{ fontSize: 11, color: COLOR_TEXT_SECONDARY }}>
                {new Date(entry.updated_at).toLocaleTimeString()}
              </Text>
            </div>
          ),
          children: (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {/* Global state */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 5 }}>
                  <GlobalOutlined style={{ fontSize: 11, color: '#1677ff' }} />
                  <Text
                    strong
                    style={{ fontSize: 11, color: COLOR_TEXT_SECONDARY, textTransform: 'uppercase', letterSpacing: 1 }}
                  >
                    Global State
                  </Text>
                </div>
                <JsonFields
                  data={entry.global_state}
                  onViewData={onViewData}
                  prefix={`iter ${entry.iteration} · global_state`}
                />
              </div>

              {/* Step state (only when non-empty) */}
              {hasStepState && (
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 5 }}>
                    <NodeIndexOutlined style={{ fontSize: 11, color: '#52c41a' }} />
                    <Text
                      strong
                      style={{ fontSize: 11, color: COLOR_TEXT_SECONDARY, textTransform: 'uppercase', letterSpacing: 1 }}
                    >
                      Step State
                    </Text>
                  </div>
                  <JsonFields
                    data={entry.step_state}
                    onViewData={onViewData}
                    prefix={`iter ${entry.iteration} · step_state`}
                  />
                </div>
              )}
            </div>
          ),
        };
      })}
    />
  );
};

export default AgentStepStatePanel;
