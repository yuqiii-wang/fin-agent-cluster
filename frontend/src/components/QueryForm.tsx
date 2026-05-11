/**
 * QueryForm — semantic test query submission form.
 *
 * Modes:
 *  - semantic test (default, implemented): query must start with "semantic test"
 *
 * On submit:
 *  1. Calls ensureGuest() to set up the guest session.
 *  2. Posts the query to /api/v1/threads/query.
 *  3. Returns the thread_id + SSE bootstrap to the parent.
 */

import React, { useState } from 'react';
import { Alert, Button, Form, Input, Radio, Space, Typography } from 'antd';
import { ensureGuest } from '../api/auth';
import { submitQuery } from '../api/threads';
import { useAuth } from '../contexts/AuthContext';
import type { QueryResponse } from '../types';

const { Title, Text } = Typography;

const MODES = [
  { label: 'Semantic Test', value: 'semantic test' },
] as const;

type Mode = (typeof MODES)[number]['value'];

interface Props {
  onSubmit: (result: QueryResponse) => void;
}

const QueryForm: React.FC<Props> = ({ onSubmit }) => {
  const { refresh: refreshAuth } = useAuth();
  const [mode, setMode] = useState<Mode>('semantic test');
  const [detail, setDetail] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    setError(null);
    setLoading(true);
    try {
      await ensureGuest();
      // Update AuthContext so UserButton and history reflect the new session.
      await refreshAuth();
      const query = detail.trim() ? `${mode}: ${detail.trim()}` : mode;
      const result = await submitQuery(query);
      onSubmit(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ maxWidth: 640, margin: '0 auto' }}>
      <Title level={4} style={{ marginBottom: 20 }}>
        Fin Agent Query
      </Title>

      <Form layout="vertical" onFinish={handleSubmit}>
        <Form.Item label={<Text strong>Mode</Text>}>
          <Radio.Group
            value={mode}
            onChange={(e) => setMode(e.target.value as Mode)}
          >
            <Space orientation="vertical">
              {MODES.map((m) => (
                <Radio key={m.value} value={m.value}>
                  {m.label}
                </Radio>
              ))}
            </Space>
          </Radio.Group>
        </Form.Item>

        <Form.Item label={<Text strong>Query detail (optional)</Text>}>
          <Input.TextArea
            value={detail}
            onChange={(e) => setDetail(e.target.value)}
            rows={3}
            placeholder="e.g. analyse AAPL for the past week"
            style={{ resize: 'none' }}
          />
          <Text type="secondary" style={{ fontSize: 11, marginTop: 4, display: 'block' }}>
            Query will be prefixed with "{mode}: "
          </Text>
        </Form.Item>

        {error && (
          <Form.Item>
            <Alert title={error} type="error" showIcon />
          </Form.Item>
        )}

        <Form.Item>
          <Button
            type="primary"
            htmlType="submit"
            loading={loading}
            size="large"
            block
          >
            {loading ? 'Submitting…' : 'Submit'}
          </Button>
        </Form.Item>
      </Form>
    </div>
  );
};

export default QueryForm;
