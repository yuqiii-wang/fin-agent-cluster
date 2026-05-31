/**
 * ServerSettings — slide-in Drawer showing current server configuration.
 *
 * Fetches GET /api/v1/system/settings on open and displays the active
 * LLM provider and model.
 */

import React, { useEffect, useState } from 'react';
import { Alert, Descriptions, Drawer, Spin, Typography } from 'antd';
import { fetchServerSettings } from '../../api/system';
import type { ServerSettingsResponse } from '../../api/system';

const { Text } = Typography;

interface Props {
  open: boolean;
  onClose: () => void;
}

const ServerSettings: React.FC<Props> = ({ open, onClose }) => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [settings, setSettings] = useState<ServerSettingsResponse | null>(null);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setError(null);
    fetchServerSettings()
      .then(setSettings)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load settings'))
      .finally(() => setLoading(false));
  }, [open]);

  return (
    <Drawer
      title="Server Settings"
      placement="right"
      size={380}
      open={open}
      onClose={onClose}
      styles={{ body: { padding: '16px 16px 24px' } }}
    >
      <Text type="secondary" style={{ display: 'block', marginBottom: 16, fontSize: 12 }}>
        Read-only — current runtime configuration.
      </Text>

      {error && (
        <Alert type="error" title={error} showIcon style={{ marginBottom: 12 }} />
      )}

      {loading ? (
        <Spin />
      ) : settings && (
        <Descriptions
          column={1}
          size="small"
          bordered
          items={[
            { key: 'llm_provider', label: 'LLM Provider', children: settings.llm.provider },
            { key: 'llm_model', label: 'LLM Model', children: settings.llm.model },
          ]}
        />
      )}
    </Drawer>
  );
};

export default ServerSettings;
