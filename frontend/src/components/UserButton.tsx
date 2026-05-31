/**
 * UserButton — top-right header widget.
 *
 * Shows a "Login" button when unauthenticated.
 * Shows an Avatar dropdown (with logout) when authenticated.
 */

import React, { useState } from 'react';
import { Avatar, Button, Dropdown, Space, Spin, Typography } from 'antd';
import { CloudServerOutlined, LogoutOutlined, SettingOutlined, UserOutlined } from '@ant-design/icons';
import type { MenuProps } from 'antd';
import { useAuth } from '../contexts/AuthContext';
import LoginModal from './LoginModal';
import UserProfile from './UserProfile';
import ServerSettings from './ServerSettings';
import type { GuestAuthResponse } from '../types';

const { Text } = Typography;

const UserButton: React.FC = () => {
  const { user, loading, refresh, logout } = useAuth();
  const [modalOpen, setModalOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [serverSettingsOpen, setServerSettingsOpen] = useState(false);

  function handleSuccess(data: GuestAuthResponse) {
    // AuthContext refresh will re-read the stored token.
    void data;
    refresh();
  }

  if (loading) return <Spin size="small" />;

  if (!user) {
    return (
      <>
        <Button type="primary" size="small" onClick={() => setModalOpen(true)}>
          Login
        </Button>
        <LoginModal
          open={modalOpen}
          onClose={() => setModalOpen(false)}
          onSuccess={handleSuccess}
        />
      </>
    );
  }

  const menuItems: MenuProps['items'] = [
    {
      key: 'info',
      label: (
        <Space direction="vertical" size={0} style={{ padding: '4px 0' }}>
          <Text strong style={{ fontSize: 13 }}>
            {user.display_name ?? user.username}
          </Text>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {user.auth_type}
          </Text>
        </Space>
      ),
      disabled: true,
    },
    { type: 'divider' },
    {
      key: 'profile',
      icon: <SettingOutlined />,
      label: 'Profile & Preferences',
      onClick: () => setProfileOpen(true),
    },
    {
      key: 'server-settings',
      icon: <CloudServerOutlined />,
      label: 'Server Settings',
      onClick: () => setServerSettingsOpen(true),
    },
    { type: 'divider' },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: 'Logout',
      danger: true,
      onClick: logout,
    },
  ];

  return (
    <>
      <Dropdown menu={{ items: menuItems }} placement="bottomRight" trigger={['click']}>
        <Avatar
          size="small"
          icon={<UserOutlined />}
          src={user.avatar_url}
          style={{ cursor: 'pointer', background: '#1677ff' }}
        />
      </Dropdown>
      <UserProfile open={profileOpen} onClose={() => setProfileOpen(false)} />
      <ServerSettings open={serverSettingsOpen} onClose={() => setServerSettingsOpen(false)} />
    </>
  );
};

export default UserButton;
