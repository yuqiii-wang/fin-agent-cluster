/**
 * AgentSkillsPanel — unified skills list combining:
 *   • Built-in skills: hardcoded markdown files from the node's skills/ directory,
 *     always active and non-deleteable (they are wired directly into the streaming
 *     LLM task and cannot be removed at runtime).
 *   • User-defined skills: runtime instructions added by the user; can be forgotten.
 *
 * Both kinds are shown in a single list.  Built-in skills appear first.
 */

import React, { useState } from 'react';
import { Button, Collapse, Dropdown, Form, Input, Modal, Space, Tag, Tooltip, Typography } from 'antd';
import type { MenuProps } from 'antd';
import { CheckOutlined, DeleteOutlined, DownOutlined, LockOutlined, PlusOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { COLOR_ACCENT_PURPLE, COLOR_BRAND_BLUE, COLOR_STATUS_SUCCESS, COLOR_SUBGRAPH_INDICATOR_DIM, COLOR_SURFACE_RAISED, COLOR_TEXT_SECONDARY } from '../../../constants/styleColors';
import type { NodeSkillFile, Skill, ToolInfo } from '../../../types';

const { Text } = Typography;
const { TextArea } = Input;

type SkillScope = 'tools' | 'system' | 'dynamic';

interface SkillScopeState {
  scope: SkillScope | null;
  boundTools: Set<string>;
}

interface AddSkillFormValues {
  summary: string;
  instructions: string;
}

interface Props {
  skills: Skill[];
  nodeSkillFiles: NodeSkillFile[];
  nodeRunning: boolean;
  /** When true the node has reached a terminal state — skills are shown in
   *  read-only/immutable style.  Add/Forget controls are hidden. */
  readonly?: boolean;
  tools: ToolInfo[];
  onAdd: (summary: string, instructions: string) => Promise<void>;
  onForget: (skillId: string) => Promise<void>;
}

function buildScopesItems(
  tools: ToolInfo[],
  disabled: boolean,
  state: SkillScopeState,
  onSetScope: (scope: SkillScope) => void,
  onToggleTool: (toolName: string) => void,
): MenuProps['items'] {
  return [
    {
      key: 'tools',
      label: (
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {state.scope === 'tools' && <CheckOutlined style={{ color: COLOR_BRAND_BLUE, fontSize: 11 }} />}
          tools
        </span>
      ),
      disabled,
      children: tools.length > 0
        ? tools.map((tool) => ({
            key: `tool_${tool.name}`,
            label: (
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                {state.boundTools.has(tool.name)
                  ? <CheckOutlined style={{ color: COLOR_STATUS_SUCCESS, fontSize: 11 }} />
                  : <span style={{ display: 'inline-block', width: 17 }} />}
                {tool.name}
              </span>
            ),
            onClick: ({ domEvent }: { domEvent: React.MouseEvent }) => {
              domEvent.stopPropagation();
              onSetScope('tools');
              onToggleTool(tool.name);
            },
          }))
        : [{ key: 'no_tools', label: 'No tools available', disabled: true }],
    },
    {
      key: 'system',
      label: (
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {state.scope === 'system' && <CheckOutlined style={{ color: COLOR_BRAND_BLUE, fontSize: 11 }} />}
          system
        </span>
      ),
      disabled,
      onClick: () => onSetScope('system'),
    },
    {
      key: 'dynamic',
      label: (
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {state.scope === 'dynamic' && <CheckOutlined style={{ color: COLOR_BRAND_BLUE, fontSize: 11 }} />}
          dynamic
        </span>
      ),
      disabled,
      onClick: () => onSetScope('dynamic'),
    },
  ];
}

function scopeBtnLabel(state: SkillScopeState): React.ReactNode {
  if (!state.scope) return <span style={{ opacity: 0.4 }}>scope</span>;
  if (state.scope === 'tools') {
    const n = state.boundTools.size;
    return <span>{state.scope}{n > 0 ? ` (${n})` : ''}</span>;
  }
  return <span>{state.scope}</span>;
}

interface HardcodedSkillLabelProps {
  sf: NodeSkillFile;
  tools: ToolInfo[];
  scopeState: SkillScopeState;
  onSetScope: (scope: SkillScope) => void;
  onToggleTool: (toolName: string) => void;
}

const HardcodedSkillLabel: React.FC<HardcodedSkillLabelProps> = ({
  sf,
  tools,
  scopeState,
  onSetScope,
  onToggleTool,
}) => {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%' }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <LockOutlined style={{ fontSize: 12, color: COLOR_ACCENT_PURPLE }} />
      <Text style={{ fontSize: 12 }}>{sf.filename.replace(/\.md$/, '')}</Text>
      <Tooltip title="Hardcoded into the node's streaming LLM task — always active and cannot be removed at runtime">
        <Tag color="purple" style={{ fontSize: 10, marginLeft: 'auto', cursor: 'help' }}>hardcoded</Tag>
      </Tooltip>
      {hovered && (
        <Dropdown
          menu={{ items: buildScopesItems(tools, true, scopeState, onSetScope, onToggleTool) }}
          trigger={['click']}
          placement="bottomRight"
        >
          <Button
            size="small"
            type="text"
            style={{ fontSize: 11 }}
            onClick={(e) => e.stopPropagation()}
          >
            {scopeBtnLabel(scopeState)} <DownOutlined style={{ fontSize: 9 }} />
          </Button>
        </Dropdown>
      )}
    </div>
  );
};

const AgentSkillsPanel: React.FC<Props> = ({ skills, nodeSkillFiles, nodeRunning, readonly = false, tools, onAdd, onForget }) => {
  const [addOpen, setAddOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [forgettingId, setForgettingId] = useState<string | null>(null);
  const [hoveredSkillId, setHoveredSkillId] = useState<string | null>(null);
  const [scopeStates, setScopeStates] = useState<Record<string, SkillScopeState>>({});
  const [form] = Form.useForm<AddSkillFormValues>();

  const getScopeState = (key: string): SkillScopeState =>
    scopeStates[key] ?? { scope: null, boundTools: new Set() };

  const handleSetScope = (key: string, scope: SkillScope) => {
    setScopeStates((prev) => ({
      ...prev,
      [key]: {
        scope,
        boundTools: scope !== 'tools' ? new Set<string>() : (prev[key]?.boundTools ?? new Set<string>()),
      },
    }));
  };

  const handleToggleTool = (key: string, toolName: string) => {
    setScopeStates((prev) => {
      const current = prev[key] ?? { scope: 'tools' as SkillScope, boundTools: new Set<string>() };
      const newBound = new Set(current.boundTools);
      if (newBound.has(toolName)) newBound.delete(toolName);
      else newBound.add(toolName);
      return { ...prev, [key]: { ...current, boundTools: newBound } };
    });
  };

  const activeSkills = skills.filter((s) => s.status === 'active');
  const totalCount = nodeSkillFiles.length + activeSkills.length;

  const handleAdd = async () => {
    const values = await form.validateFields();
    setAdding(true);
    try {
      await onAdd(values.summary.trim(), values.instructions.trim());
      form.resetFields();
      setAddOpen(false);
    } finally {
      setAdding(false);
    }
  };

  const handleForget = async (skillId: string) => {
    setForgettingId(skillId);
    try {
      await onForget(skillId);
    } finally {
      setForgettingId(null);
    }
  };

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <Text strong style={{ fontSize: 12, color: COLOR_TEXT_SECONDARY }}>
          SKILLS ({totalCount})
        </Text>
        {!readonly && (
          <Button
            size="small"
            type="text"
            icon={<PlusOutlined />}
            onClick={() => setAddOpen(true)}
            style={{ marginLeft: 'auto', fontSize: 11 }}
          >
            Add skill
          </Button>
        )}
      </div>

      {totalCount === 0 && (
        <Text type="secondary" style={{ fontSize: 12 }}>No skills added yet.</Text>
      )}

      {/* ── Built-in skills (hardcoded into the streaming LLM task) ─────── */}
      {nodeSkillFiles.length > 0 && (
        <Collapse
          size="small"
          ghost
          style={{ marginBottom: 4 }}
          items={nodeSkillFiles.map((sf) => ({
            key: sf.filename,
            style: readonly ? { opacity: 0.55 } : undefined,
            label: (
              <HardcodedSkillLabel
                sf={sf}
                tools={tools}
                scopeState={getScopeState(sf.filename)}
                onSetScope={(scope) => handleSetScope(sf.filename, scope)}
                onToggleTool={(toolName) => handleToggleTool(sf.filename, toolName)}
              />
            ),
            children: (
              <pre style={{ fontSize: 11, margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 320, overflow: 'auto' }}>
                {sf.content}
              </pre>
            ),
          }))}
        />
      )}

      {/* ── User-defined runtime skills ────────────────────────────────── */}
      {activeSkills.map((skill) => (
        <div
          key={skill.skill_id}
          style={{
            padding: '6px 10px',
            marginBottom: 4,
            borderRadius: 4,
            borderLeft: `3px solid ${readonly ? COLOR_SUBGRAPH_INDICATOR_DIM : COLOR_ACCENT_PURPLE}`,
            background: COLOR_SURFACE_RAISED,
            opacity: readonly ? 0.55 : 1,
          }}
          onMouseEnter={() => !readonly && setHoveredSkillId(skill.skill_id)}
          onMouseLeave={() => setHoveredSkillId(null)}
        >
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
            <ThunderboltOutlined style={{ fontSize: 12, color: COLOR_ACCENT_PURPLE, marginTop: 2 }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <Text strong style={{ fontSize: 12 }}>{skill.summary}</Text>
              <Text
                type="secondary"
                style={{ fontSize: 11, display: 'block', marginTop: 2, whiteSpace: 'pre-wrap' }}
              >
                {skill.instructions}
              </Text>
            </div>
            {hoveredSkillId === skill.skill_id && (
              <Dropdown
                menu={{
                  items: buildScopesItems(
                    tools,
                    false,
                    getScopeState(skill.skill_id),
                    (scope) => handleSetScope(skill.skill_id, scope),
                    (toolName) => handleToggleTool(skill.skill_id, toolName),
                  ),
                }}
                trigger={['click']}
                placement="bottomRight"
              >
                <Button size="small" type="text" style={{ fontSize: 11 }}>
                  {scopeBtnLabel(getScopeState(skill.skill_id))} <DownOutlined style={{ fontSize: 9 }} />
                </Button>
              </Dropdown>
            )}
            {!readonly && (
              <Tooltip title="Forget skill (stops applying to future runs)">
                <Button
                  size="small"
                  type="text"
                  danger
                  icon={<DeleteOutlined />}
                  loading={forgettingId === skill.skill_id}
                  onClick={() => handleForget(skill.skill_id)}
                  style={{ padding: '0 4px' }}
                />
              </Tooltip>
            )}
          </div>
        </div>
      ))}

      <Modal
        open={addOpen}
        title="Add skill"
        okText="Add"
        confirmLoading={adding}
        onOk={handleAdd}
        onCancel={() => { setAddOpen(false); form.resetFields(); }}
        destroyOnClose
      >
        <Space direction="vertical" style={{ width: '100%', marginTop: 8 }} size="small">
          {nodeRunning && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              The agent will pause and restart with this skill applied to its context.
            </Text>
          )}
          <Form form={form} layout="vertical" autoComplete="off">
            <Form.Item
              name="summary"
              label="Summary"
              rules={[{ required: true, message: 'Please enter a summary' }]}
            >
              <Input placeholder="One-line label, e.g. Focus on APAC markets" />
            </Form.Item>
            <Form.Item
              name="instructions"
              label="Instructions"
              rules={[{ required: true, message: 'Please enter instructions' }]}
            >
              <TextArea
                rows={4}
                placeholder="Full instruction text appended to the agent's system prompt…"
              />
            </Form.Item>
          </Form>
        </Space>
      </Modal>
    </>
  );
};

export default AgentSkillsPanel;
