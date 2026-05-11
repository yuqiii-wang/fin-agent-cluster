/**
 * UserHistory — sidebar panel with a "New Query" button and thread history list.
 */

import React from 'react';
import { Button, Typography } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import HistoryList from './HistoryList';
import type { ThreadSummary } from '../../types';

const { Text } = Typography;

interface Props {
  history: ThreadSummary[];
  activeId: string | null;
  isAuthenticated: boolean;
  onSelect: (threadId: string) => void;
  onNewQuery: () => void;
}

const UserHistory: React.FC<Props> = ({ history, activeId, isAuthenticated, onSelect, onNewQuery }) => (
  <div style={{ padding: '12px 8px' }}>
    <Button
      type="dashed"
      icon={<PlusOutlined />}
      block
      onClick={onNewQuery}
      style={{ marginBottom: 12 }}
    >
      New Query
    </Button>

    {!isAuthenticated && (
      <Text type="secondary" style={{ fontSize: 11, display: 'block', textAlign: 'center', marginBottom: 8 }}>
        Login to persist history
      </Text>
    )}

    <HistoryList history={history} activeId={activeId} onSelect={onSelect} />
  </div>
);

export default UserHistory;
