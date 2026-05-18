/**
 * ReExploreModal — modal dialog for re-exploring a graph node with optional input override.
 *
 * For regular (non-conditional) nodes, shows the node's current input as an editable JSON
 * block and forks directly from that node.
 *
 * For conditional topology-only nodes, the fork must come from the actual predecessor node
 * that made the routing decision.  The modal shows which node will be forked, lets the user
 * edit that node's input, and — when multiple parallel-branch predecessors exist — provides
 * a dropdown so the user can choose which branch endpoint to fork from.
 *
 * onConfirm is always called with the actual node ID of the fork point (never a
 * topology- placeholder) so the backend request is always an end-lifecycle node.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Button, Modal, Select, Space, Tag, Typography } from 'antd';
import { BranchesOutlined } from '@ant-design/icons';
import { COLOR_BORDER_BASE, COLOR_DANGER, COLOR_SURFACE_BASE, COLOR_TEXT_BODY } from '../../constants/styleColors';
import type { NodeInfo } from '../../types';

const { Text, Paragraph } = Typography;

interface Props {
  open: boolean;
  /** The node the user clicked Re-explore on (may be a conditional topology-only placeholder). */
  node: NodeInfo | null;
  loading: boolean;
  /**
   * Actual predecessor nodes to fork from, resolved from the graph topology for
   * conditional topology-only nodes.  When there is more than one candidate
   * (parallel branches all routing to this conditional node) a dropdown is shown.
   * Undefined for regular non-conditional nodes — fork happens from node itself.
   */
  prevNodes?: NodeInfo[];
  /** Called with the actual node ID to fork from and an optional input override. */
  onConfirm: (forkNodeId: string, inputOverride?: Record<string, unknown>) => void;
  onCancel: () => void;
}

function jsonEqual(a: unknown, b: unknown): boolean {
  try {
    return JSON.stringify(a) === JSON.stringify(b);
  } catch {
    return false;
  }
}

const ReExploreModal: React.FC<Props> = ({ open, node, loading, prevNodes, onConfirm, onCancel }) => {
  // Which prev-node branch the user has selected (for the multi-branch dropdown).
  // null means "use the first/only prev node".
  const [selectedPrevNodeId, setSelectedPrevNodeId] = useState<string | null>(null);
  const [editText, setEditText] = useState('');
  const [parseError, setParseError] = useState<string | null>(null);
  const [sameInputWarning, setSameInputWarning] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // The prev node currently in focus (for conditional nodes) or null (regular nodes).
  const activePrevNode: NodeInfo | null = prevNodes
    ? (prevNodes.find(n => n.node_id === selectedPrevNodeId) ?? prevNodes[0] ?? null)
    : null;

  // The actual node whose checkpoint we will fork from.
  const forkNode: NodeInfo | null = activePrevNode ?? node;
  const originalInput = forkNode?.input ?? null;
  const hasInput = !!originalInput && Object.keys(originalInput).length > 0;

  // Reset editor state when the modal opens for a different node or when the
  // selected prev node changes.
  useEffect(() => {
    if (open && forkNode) {
      const text = forkNode.input ? JSON.stringify(forkNode.input, null, 2) : '{}';
      setEditText(text);
      setParseError(null);
      setSameInputWarning(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, node?.node_id, selectedPrevNodeId]);

  // Reset the branch selection whenever the modal opens for a new target node.
  useEffect(() => {
    if (open) setSelectedPrevNodeId(null);
  }, [open, node?.node_id]);

  const handleTextChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setEditText(e.target.value);
    setParseError(null);
    setSameInputWarning(false);
  }, []);

  const handleConfirm = useCallback(() => {
    if (!forkNode) return;
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
    onConfirm(forkNode.node_id, override);
  }, [forkNode, editText, originalInput, sameInputWarning, onConfirm]);

  const isConditionalTarget = prevNodes !== undefined;
  const noPrevNodesFound = isConditionalTarget && prevNodes.length === 0;

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
            onClick={handleConfirm}
            disabled={!forkNode || noPrevNodesFound}
            danger={sameInputWarning}
          >
            {sameInputWarning ? 'Confirm anyway' : 'Re-explore'}
          </Button>
        </Space>
      }
      width={560}
      destroyOnHidden
    >
      {/* ── Conditional-node header ─────────────────────────────────────── */}
      {isConditionalTarget && (
        <div style={{ marginBottom: 16 }}>
          <Paragraph type="secondary" style={{ marginBottom: 8 }}>
            <Text strong>{node?.node_name}</Text> has not run — the graph will be forked
            from the node that made the routing decision.
          </Paragraph>

          {noPrevNodesFound ? (
            <Alert
              type="error"
              message="No predecessor node found for this conditional branch."
              showIcon
            />
          ) : prevNodes.length > 1 ? (
            <div>
              <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                Select which branch endpoint to fork from:
              </Text>
              <Select
                value={activePrevNode?.node_id}
                onChange={setSelectedPrevNodeId}
                style={{ width: '100%' }}
                options={prevNodes.map(n => ({ label: n.node_name, value: n.node_id }))}
              />
            </div>
          ) : (
            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>Forking from: </Text>
              <Tag color="blue">{activePrevNode?.node_name}</Tag>
            </div>
          )}
        </div>
      )}

      {/* ── Input editor (same UI for both conditional and regular nodes) ── */}
      {forkNode && !noPrevNodesFound && (
        <>
          {isConditionalTarget && activePrevNode && (
            <Paragraph type="secondary" style={{ marginBottom: 8 }}>
              <Text strong>{activePrevNode.node_name}</Text> will be re-explored from its checkpoint.
            </Paragraph>
          )}

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
