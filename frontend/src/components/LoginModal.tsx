/**
 * LoginModal — login / register modal.
 *
 * Phase 1 supports guest identity only.  The modal can be extended to add
 * email/password or OAuth flows in future without changing the embedding API.
 *
 * When the user clicks "Continue as Guest" the component calls
 * ``ensureGuest()`` to create/restore a guest session and stores the
 * returned token, then notifies the parent via ``onSuccess``.
 */

import React, { useState } from 'react';
import { Alert, Button, Divider, Modal, Space, Typography } from 'antd';
import { CloseOutlined, UserOutlined } from '@ant-design/icons';
import { ensureGuest } from '../api/auth';
import type { GuestAuthResponse } from '../types';

const { Text, Title } = Typography;

interface Props {
  open: boolean;
  onClose: () => void;
  onSuccess: (user: GuestAuthResponse) => void;
}

const LoginModal: React.FC<Props> = ({ open, onClose, onSuccess }) => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorHovered, setErrorHovered] = useState(false);

  async function handleGuest() {
    setLoading(true);
    setError(null);
    try {
      const user = await ensureGuest();
      onSuccess(user);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create guest session');
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      centered
      width={380}
      title={
        <Title level={4} style={{ margin: 0 }}>
          Sign in to Fin Agent
        </Title>
      }
    >
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        {error && (
          <Alert
            type="error"
            message={error}
            showIcon
            closable
            closeIcon={<CloseOutlined style={{ visibility: errorHovered ? 'visible' : 'hidden' }} />}
            onClose={() => setError(null)}
            onMouseEnter={() => setErrorHovered(true)}
            onMouseLeave={() => setErrorHovered(false)}
          />
        )}

        <Text type="secondary" style={{ fontSize: 13 }}>
          Your thread history is persisted across sessions when you sign in.
        </Text>

        <Divider style={{ margin: '8px 0' }}>Quick access</Divider>

        <Button
          block
          size="large"
          icon={<UserOutlined />}
          loading={loading}
          onClick={handleGuest}
        >
          Continue as Guest
        </Button>
      </Space>
    </Modal>
  );
};

export default LoginModal;
