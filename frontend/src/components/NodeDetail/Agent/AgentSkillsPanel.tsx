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
import { Button, Collapse, Dropdown, Form, Input, message, Modal, Space, Tag, Tooltip, Typography } from 'antd';
import type { MenuProps } from 'antd';
import { DeleteOutlined, DownOutlined, LockOutlined, PlusOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { COLOR_SURFACE_RAISED, COLOR_TEXT_SECONDARY } from '../../../constants/styleColors';
import type { NodeSkillFile, Skill, ToolInfo } from '../../../types';

const { Text } = Typography;
const { TextArea } = Input;

interface AddSkillFormValues {
  summary: string;
  instructions: string;
}

interface Props {
  skills: Skill[];
  nodeSkillFiles: NodeSkillFile[];
  nodeRunning: boolean;
  tools: ToolInfo[];
  onAdd: (summary: string, instructions: string) => Promise<void>;
  onForget: (skillId: string) => Promise<void>;
}

function buildScopesItems(tools: ToolInfo[], disabled: boolean): MenuProps['items'] {
  return [
    {
      key: 'bind_to_tools',
      label: 'Bind to tools',
      disabled,
      children: tools.length > 0
        ? tools.map((tool) => ({
            key: `tool_${tool.name}`,
            label: tool.name,
            disabled,
            onClick: () => message.warning('Not yet implemented'),
          }))
        : [{ key: 'no_tools', label: 'No tools available', disabled: true }],
    },
    {
      key: 'bind_as_system_prompt',
      label: 'Bind to agent as system prompt',
      disabled,
      onClick: () => message.warning('Not yet implemented'),
    },
    {
      key: 'bind_to_tools_dynamically',
      label: 'Bind to tools dynamically',
      disabled,
      onClick: () => message.warning('Not yet implemented'),
    },
  ];
}

const HardcodedSkillLabel: React.FC<{ sf: NodeSkillFile; scopesItems: MenuProps['items'] }> = ({
  sf,
  scopesItems,
}) => {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%' }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <LockOutlined style={{ fontSize: 12, color: '#722ed1' }} />
      <Text style={{ fontSize: 12 }}>{sf.filename.replace(/\.md$/, '')}</Text>
      <Tooltip title="Hardcoded into the node's streaming LLM task — always active and cannot be removed at runtime">
        <Tag color="purple" style={{ fontSize: 10, marginLeft: 'auto', cursor: 'help' }}>hardcoded</Tag>
      </Tooltip>
      {hovered && (
        <Dropdown menu={{ items: scopesItems }} trigger={['click']} placement="bottomRight">
          <Button
            size="small"
            type="text"
            style={{ fontSize: 11 }}
            onClick={(e) => e.stopPropagation()}
          >
            Scopes <DownOutlined style={{ fontSize: 9 }} />
          </Button>
        </Dropdown>
      )}
    </div>
  );
};

const AgentSkillsPanel: React.FC<Props> = ({ skills, nodeSkillFiles, nodeRunning, tools, onAdd, onForget }) => {
  const [addOpen, setAddOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [forgettingId, setForgettingId] = useState<string | null>(null);
  const [hoveredSkillId, setHoveredSkillId] = useState<string | null>(null);
  const [form] = Form.useForm<AddSkillFormValues>();

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
        <Button
          size="small"
          type="text"
          icon={<PlusOutlined />}
          onClick={() => setAddOpen(true)}
          style={{ marginLeft: 'auto', fontSize: 11 }}
        >
          Add skill
        </Button>
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
            label: (
              <HardcodedSkillLabel sf={sf} scopesItems={buildScopesItems(tools, true)} />
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
            borderLeft: '3px solid #722ed1',
            background: COLOR_SURFACE_RAISED,
          }}
          onMouseEnter={() => setHoveredSkillId(skill.skill_id)}
          onMouseLeave={() => setHoveredSkillId(null)}
        >
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
            <ThunderboltOutlined style={{ fontSize: 12, color: '#722ed1', marginTop: 2 }} />
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
                menu={{ items: buildScopesItems(tools, false) }}
                trigger={['click']}
                placement="bottomRight"
              >
                <Button size="small" type="text" style={{ fontSize: 11 }}>
                  Scopes <DownOutlined style={{ fontSize: 9 }} />
                </Button>
              </Dropdown>
            )}
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
