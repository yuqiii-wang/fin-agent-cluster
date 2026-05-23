/**
 * MainQuery — production query entry point.
 *
 * Renders a centered chat-style input field on the page.  On submit it calls
 * /api/v1/threads/query and hands the result to the parent via onSubmit.
 */

import React, { useState } from 'react';
import { Alert, Input, Typography } from 'antd';
import { CloseOutlined } from '@ant-design/icons';
import { ensureGuest } from '../../api/auth';
import { submitQuery } from '../../api/threads';
import { useAuth } from '../../contexts/AuthContext';
import type { QueryResponse } from '../../types';

const { Title, Text } = Typography;

interface Props {
  onSubmit: (result: QueryResponse) => void;
}

const MainQuery: React.FC<Props> = ({ onSubmit }) => {
  const { refresh: refreshAuth } = useAuth();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorHovered, setErrorHovered] = useState(false);

  async function handleSearch(value: string) {
    const query = value.trim();
    if (!query) return;
    setError(null);
    setLoading(true);
    try {
      await ensureGuest();
      await refreshAuth();
      const result = await submitQuery(query);
      onSubmit(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        padding: '0 24px',
        gap: 24,
      }}
    >
      <div style={{ textAlign: 'center' }}>
        <Title level={2} style={{ color: '#fff', marginBottom: 4 }}>
          Fin Agent
        </Title>
        <Text style={{ color: '#888' }}>Ask a financial question to get started</Text>
      </div>

      <Input.Search
        placeholder="e.g. Analyse AAPL outlook for Q3 2026"
        enterButton="Ask"
        size="large"
        loading={loading}
        disabled={loading}
        onSearch={handleSearch}
        style={{ maxWidth: 640, width: '100%' }}
        styles={{
          input: { background: '#1a1a1a', borderColor: '#333', color: '#fff' },
        }}
      />

      {error && (
        <Alert
          type="error"
          message={error}
          closable
          closeIcon={<CloseOutlined style={{ visibility: errorHovered ? 'visible' : 'hidden' }} />}
          onClose={() => setError(null)}
          onMouseEnter={() => setErrorHovered(true)}
          onMouseLeave={() => setErrorHovered(false)}
          style={{ maxWidth: 640, width: '100%' }}
        />
      )}
    </div>
  );
};

export default MainQuery;
