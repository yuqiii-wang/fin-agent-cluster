/**
 * UserProfile — slide-in Drawer that shows user identity and per-node
 * agent preferences.
 *
 * Preferences are loaded from GET /api/v1/users/me/preferences and each
 * node's config is saved individually via PUT /api/v1/users/me/preferences/:node.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Avatar,
  Badge,
  Collapse,
  Drawer,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';
import { CloseOutlined, UserOutlined } from '@ant-design/icons';
import { useAuth } from '../../contexts/AuthContext';
import { fetchPreferences, upsertPreference } from '../../api/user';
import { fetchNodeMetas } from '../../api/threads';
import NodePrefCard from './NodePrefCard';
import type { NodeConfig, NodeMeta, UserPreference } from '../../types';

const { Text, Title } = Typography;

interface Props {
  open: boolean;
  onClose: () => void;
}

const UserProfile: React.FC<Props> = ({ open, onClose }) => {
  const { user } = useAuth();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorHovered, setErrorHovered] = useState(false);
  const [nodeMetas, setNodeMetas] = useState<NodeMeta[]>([]);
  /** Local state: node_name → NodeConfig */
  const [configs, setConfigs] = useState<Record<string, NodeConfig>>({});
  /** node_names currently being saved */
  const [saving, setSaving] = useState<Set<string>>(new Set());
  const saveTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  // ---- load preferences and node metas on open ----
  useEffect(() => {
    if (!open || !user) return;
    setLoading(true);
    setError(null);
    Promise.all([fetchPreferences(), fetchNodeMetas()])
      .then(([prefs, metas]: [UserPreference[], NodeMeta[]]) => {
        const map: Record<string, NodeConfig> = {};
        for (const p of prefs) map[p.node_name] = p.config;
        setConfigs(map);
        setNodeMetas(metas);
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : 'Failed to load preferences');
      })
      .finally(() => setLoading(false));
  }, [open, user]);

  // ---- debounced save per node ----
  const handleChange = useCallback((nodeName: string, patch: NodeConfig) => {
    setConfigs((prev) => ({ ...prev, [nodeName]: patch }));

    // Cancel any pending save for this node.
    if (saveTimers.current[nodeName]) clearTimeout(saveTimers.current[nodeName]);

    saveTimers.current[nodeName] = setTimeout(async () => {
      setSaving((prev) => new Set(prev).add(nodeName));
      try {
        await upsertPreference(nodeName, patch);
      } catch {
        // Non-fatal — user sees stale saving indicator.
      } finally {
        setSaving((prev) => {
          const next = new Set(prev);
          next.delete(nodeName);
          return next;
        });
      }
    }, 600);
  }, []);

  if (!user) return null;

  return (
    <Drawer
      title="Profile & Agent Preferences"
      placement="right"
      width={420}
      open={open}
      onClose={onClose}
      styles={{ body: { padding: '16px 16px 24px' } }}
    >
      {/* ---- User identity ---- */}
      <Space align="start" style={{ marginBottom: 20 }}>
        <Avatar size={48} icon={<UserOutlined />} src={user.avatar_url} />
        <Space direction="vertical" size={0}>
          <Title level={5} style={{ margin: 0 }}>
            {user.display_name ?? user.username}
          </Title>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {user.email ?? user.username}
          </Text>
          <Tag style={{ marginTop: 4 }}>{user.auth_type}</Tag>
        </Space>
      </Space>

      {/* ---- Agent preferences ---- */}
      <Text strong style={{ display: 'block', marginBottom: 10 }}>
        Agent Node Preferences
      </Text>

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
          style={{ marginBottom: 12 }}
        />
      )}

      {loading ? (
        <Spin />
      ) : (
        <Collapse
          defaultActiveKey={['Global']}
          size="small"
          items={Array.from(new Set(nodeMetas.map((m) => m.category))).map((cat) => {
            const metas = nodeMetas.filter((m) => m.category === cat);
            return {
              key: cat,
              label: cat,
              children: metas.map((meta) => (
                <Badge.Ribbon
                  key={meta.node_name}
                  text={saving.has(meta.node_name) ? 'Saving…' : ''}
                  color="blue"
                  style={{
                    display: saving.has(meta.node_name) ? undefined : 'none',
                    fontSize: 10,
                  }}
                >
                  <NodePrefCard
                    meta={meta}
                    values={configs[meta.node_name] ?? {}}
                    onChange={handleChange}
                    saving={saving.has(meta.node_name)}
                  />
                </Badge.Ribbon>
              )),
            };
          })}
        />
      )}
    </Drawer>
  );
};

export default UserProfile;
