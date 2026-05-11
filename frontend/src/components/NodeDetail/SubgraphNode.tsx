/**
 * SubgraphNode — lists direct child nodes of a Subgraph node.
 * Each row is clickable to navigate to that child node's detail.
 */

import React, { useState } from 'react';
import { Tag, Typography } from 'antd';
import { RightOutlined } from '@ant-design/icons';
import { COLOR_SURFACE_RAISED, COLOR_TEXT_MUTED, COLOR_TEXT_SECONDARY } from '../../constants/styleColors';
import { STATUS_HEX, STATUS_TAG_COLOR } from '../../constants/statusColors';
import type { NodeInfo } from '../../types';

const { Text } = Typography;

interface Props {
  childNodes: NodeInfo[];
  onSelectNode: (nodeId: string) => void;
}

const SubgraphNode: React.FC<Props> = ({ childNodes, onSelectNode }) => {
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  if (childNodes.length === 0) {
    return <Text type="secondary" style={{ fontSize: 12 }}>No child nodes.</Text>;
  }

  return (
    <>
      <Text strong style={{ fontSize: 12, color: COLOR_TEXT_SECONDARY, display: 'block', marginBottom: 6 }}>
        NODES ({childNodes.length})
      </Text>
      {childNodes.map(n => (
        <div
          key={n.node_id}
          style={{
            cursor: 'pointer',
            borderRadius: 4,
            padding: '6px 10px',
            marginBottom: 3,
            borderLeft: `3px solid ${STATUS_HEX[n.status] ?? '#8c8c8c'}`,
            background: hoveredId === n.node_id ? COLOR_SURFACE_RAISED : 'transparent',
            transition: 'background 0.15s',
          }}
          onClick={() => onSelectNode(n.node_id)}
          onMouseEnter={() => setHoveredId(n.node_id)}
          onMouseLeave={() => setHoveredId(null)}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Text style={{ flex: 1, fontSize: 12 }}>{n.node_name}</Text>
            {n.type !== 'Typical' && <Tag style={{ fontSize: 10 }}>{n.type}</Tag>}
            <Tag color={STATUS_TAG_COLOR[n.status] ?? 'default'} style={{ fontSize: 10 }}>{n.status}</Tag>
            <RightOutlined style={{ fontSize: 10, color: COLOR_TEXT_MUTED }} />
          </div>
        </div>
      ))}
    </>
  );
};

export default SubgraphNode;
