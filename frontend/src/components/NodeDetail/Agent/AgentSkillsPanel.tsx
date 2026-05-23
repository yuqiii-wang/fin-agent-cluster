/**
 * AgentSkillsPanel — displays active skills and allows adding new ones.
 *
 * Skills are user-defined runtime instructions that are appended to the
 * agent's system prompt.  Adding a skill when the node is running triggers
 * a pause → context-update → auto-resume cycle on the backend.
 */

import React, { useState } from 'react';
import { Button, Form, Input, Modal, Space, Tag, Tooltip, Typography } from 'antd';
import { DeleteOutlined, PlusOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { COLOR_BORDER_BASE, COLOR_SURFACE_RAISED, COLOR_TEXT_SECONDARY } from '../../../constants/styleColors';
import type { Skill } from '../../../types';

const { Text } = Typography;
const { TextArea } = Input;

interface AddSkillFormValues {
  summary: string;
  instructions: string;
}

interface Props {
  skills: Skill[];
  nodeRunning: boolean;
  onAdd: (summary: string, instructions: string) => Promise<void>;
  onForget: (skillId: string) => Promise<void>;
}

const AgentSkillsPanel: React.FC<Props> = ({ skills, nodeRunning, onAdd, onForget }) => {
  const [addOpen, setAddOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [forgettingId, setForgettingId] = useState<string | null>(null);
  const [form] = Form.useForm<AddSkillFormValues>();

  const activeSkills = skills.filter((s) => s.status === 'active');

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
          SKILLS ({activeSkills.length})
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

      {activeSkills.length === 0 && (
        <Text type="secondary" style={{ fontSize: 12 }}>No skills added yet.</Text>
      )}

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
