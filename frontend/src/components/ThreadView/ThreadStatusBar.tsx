import React, { useState } from 'react';
import { Alert, Badge, Button, Card, Typography } from 'antd';
import { StopOutlined } from '@ant-design/icons';
import { COLOR_TEXT_MUTED } from '../../constants/styleColors';
import { isThreadActive } from '../../constants/lifecycleStatus';
import { STATUS_BADGE } from '../../constants/statusColors';

const { Text } = Typography;

interface Props {
  threadId: string;
  status: string;
  query: string;
  error?: string;
  cancelling: string | null;
  onCancel: () => void;
}

const ThreadStatusBar: React.FC<Props> = ({ threadId, status, query, error, cancelling, onCancel }) => {
  const [hovered, setHovered] = useState(false);

  return (
    <Card
      size="small"
      style={{ borderRadius: 8 }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <Badge status={STATUS_BADGE[status] ?? 'default'} text={status.toUpperCase()} />
        <Text type="secondary" style={{ fontSize: 12 }}>{query}</Text>
        <Text copyable code style={{ fontSize: 10, color: COLOR_TEXT_MUTED }}>{threadId}</Text>
        {isThreadActive(status) && hovered && (
          <Button
            size="small" danger icon={<StopOutlined />}
            loading={cancelling === threadId}
            onClick={onCancel}
            style={{ marginLeft: 'auto' }}
          />
        )}
      </div>
      {error && <Alert title={error} type="error" showIcon style={{ marginTop: 8 }} />}
    </Card>
  );
};

export default ThreadStatusBar;
