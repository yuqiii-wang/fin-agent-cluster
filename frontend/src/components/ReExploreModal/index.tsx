/**
 * ReExploreModal — modal dialog for re-exploring a graph node with optional input override.
 *
 * Shows the node's current input as an editable JSON block.
 * If the user submits without changes, a warning notice is shown.
 * On confirm, calls onConfirm with the edited input (or undefined if unchanged).
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Button, Modal, Space, Tag, Typography } from 'antd';
import { BranchesOutlined } from '@ant-design/icons';
import { COLOR_BORDER_BASE, COLOR_DANGER, COLOR_SURFACE_BASE, COLOR_TEXT_BODY } from '../../constants/styleColors';
import type { NodeInfo } from '../../types';

const { Text, Paragraph } = Typography;

interface Props {
  open: boolean;
  node: NodeInfo | null;
  loading: boolean;
  onConfirm: (inputOverride?: Record<string, unknown>) => void;
  onCancel: () => void;
  /** Condition labels for conditional not-yet-run nodes (from topology edges). */
  conditions?: string[];
}

function jsonEqual(a: unknown, b: unknown): boolean {
  try {
    return JSON.stringify(a) === JSON.stringify(b);
  } catch {
    return false;
  }
}

const ReExploreModal: React.FC<Props> = ({ open, node, loading, onConfirm, onCancel, conditions }) => {
  const originalInput = node?.input ?? null;
  const [editText, setEditText] = useState('');
  const [parseError, setParseError] = useState<string | null>(null);
  const [sameInputWarning, setSameInputWarning] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Reset editor state when modal opens with a new node.
  useEffect(() => {
    if (open && node) {
      const text = node.input ? JSON.stringify(node.input, null, 2) : '{}';
      setEditText(text);
      setParseError(null);
      setSameInputWarning(false);
    }
  }, [open, node?.node_id]);

  const handleTextChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setEditText(e.target.value);
    setParseError(null);
    setSameInputWarning(false);
  }, []);

  const handleConfirm = useCallback(() => {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(editText);
    } catch {
      setParseError('Invalid JSON — please fix the input before confirming.');
      return;
    }

    // Warn if input is identical to original.
    if (jsonEqual(parsed, originalInput) || (Object.keys(parsed).length === 0 && !originalInput)) {
      if (!sameInputWarning) {
        setSameInputWarning(true);
        return; // First click: show warning, require second click to confirm.
      }
    }

    // If empty object and no original input, pass undefined (no override).
    const override = Object.keys(parsed).length === 0 ? undefined : parsed;
    onConfirm(override);
  }, [editText, originalInput, sameInputWarning, onConfirm]);

  const isTopologyOnly = !!node?.is_topology_only;
  const hasInput = !!node?.input && Object.keys(node.input).length > 0;

  return (
    <Modal
      open={open}
      title={
        <Space>
          <BranchesOutlined />
          <span>Re-explore: {node?.node_name}</span>
        </Space>
      }
      onCancel={onCancel}
      footer={
        <Space>
          <Button onClick={onCancel} disabled={loading}>
            Cancel
          </Button>
          <Button
            type="primary"
            icon={<BranchesOutlined />}
            loading={loading}
            onClick={isTopologyOnly ? () => onConfirm(undefined) : handleConfirm}
            danger={!isTopologyOnly && sameInputWarning}
          >
            {!isTopologyOnly && sameInputWarning ? 'Confirm anyway' : 'Re-explore'}
          </Button>
        </Space>
      }
      width={560}
      destroyOnHidden
    >
      {isTopologyOnly ? (
        <>
          <Paragraph type="secondary" style={{ marginBottom: 12 }}>
            This node has not run. It will execute when the following condition is met:
          </Paragraph>
          {conditions?.length ? (
            <div style={{ marginBottom: 12, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {conditions.map((c, i) => (
                <Tag key={i} color="blue">{c}</Tag>
              ))}
            </div>
          ) : (
            <Paragraph type="secondary" style={{ marginBottom: 12 }}>
              No condition labels available.
            </Paragraph>
          )}
          <Paragraph type="secondary" style={{ fontSize: 12 }}>
            Re-exploring forks the graph just before the routing decision, allowing this
            branch to run if conditions are met.
          </Paragraph>
        </>
      ) : (
        <>
          {!hasInput ? (
            <Paragraph type="secondary" style={{ marginBottom: 12 }}>
              This node takes no explicit input — it reads directly from the graph state.
              Re-exploring will re-run from the same state checkpoint.
            </Paragraph>
          ) : (
            <Paragraph type="secondary" style={{ marginBottom: 8 }}>
              Edit the node input below. Changed values will be injected into the forked
              checkpoint before the branch runs.
            </Paragraph>
          )}

          <textarea
            ref={textareaRef}
            value={editText}
            onChange={handleTextChange}
            style={{
              width: '100%',
              minHeight: 200,
              fontFamily: 'monospace',
              fontSize: 12,
              padding: '8px 10px',
              border: `1px solid ${parseError ? COLOR_DANGER : COLOR_BORDER_BASE}`,
              borderRadius: 6,
              background: COLOR_SURFACE_BASE,
              color: COLOR_TEXT_BODY,
              resize: 'vertical',
              outline: 'none',
              boxSizing: 'border-box',
            }}
            spellCheck={false}
          />

          {parseError && (
            <Alert
              type="error"
              message={parseError}
              showIcon
              style={{ marginTop: 8 }}
            />
          )}

          {sameInputWarning && !parseError && (
            <Alert
              type="warning"
              message="Same input would likely trigger the same graph executions."
              description="Click 'Confirm anyway' to proceed with identical input."
              showIcon
              style={{ marginTop: 8 }}
            />
          )}

          {!hasInput && (
            <Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 8 }}>
              Tip: you can still inject GraphState overrides as JSON key-value pairs.
            </Text>
          )}
        </>
      )}
    </Modal>
  );
};

export default ReExploreModal;
