/**
 * HistoryItem — single thread entry row in the history sidebar.
 */

import React from 'react';
import { Badge, Typography } from 'antd';
import { STATUS_BADGE } from '../../constants/statusColors';
import type { ThreadSummary } from '../../types';

const { Text } = Typography;

interface Props {
  entry: ThreadSummary;
  isActive: boolean;
  onClick: () => void;
}

const HistoryItem: React.FC<Props> = ({ entry, isActive, onClick }) => (
  <div
    style={{
      cursor: 'pointer',
      borderRadius: 6,
      padding: '6px 8px',
      marginBottom: 4,
      background: isActive ? 'rgba(22,119,255,0.15)' : 'transparent',
    }}
    onClick={onClick}
  >
    <Text
      style={{
        fontSize: 12,
        color: isActive ? '#1677ff' : '#bfbfbf',
        display: 'block',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
        maxWidth: 200,
      }}
    >
      {entry.query}
    </Text>
    <Badge
      status={STATUS_BADGE[entry.status] ?? 'default'}
      text={
        <Text style={{ fontSize: 10, color: '#595959' }}>
          {entry.status}
        </Text>
      }
    />
  </div>
);

export default HistoryItem;
