/**
 * QueryForm — query submission form.
 *
 * Modes:
 *  - question: free-text financial question (default)
 *  - semantic test: query starts with "semantic test [tps=N dur=N]"
 *  - concurrency test: fires N parallel requests each as "concurrency test [tps=N dur=N]"
 *
 * On submit:
 *  1. Calls ensureGuest() to create/restore a guest session (auto-login).
 *  2. Refreshes AuthContext so the header reflects the logged-in state.
 *  3. Posts the query (or N queries) to /api/v1/threads/query.
 *  4. Returns the results to the parent via onSubmit / onConcurrencySubmit.
 */

import React, { useState } from 'react';
import { Alert, Button, Form, Input, InputNumber, Radio, Space, Typography } from 'antd';
import { v4 as uuidv4 } from 'uuid';
import { ensureGuest } from '../api/auth';
import { submitQuery } from '../api/threads';
import { useAuth } from '../contexts/AuthContext';
import type { QueryResponse } from '../types';

const { Title, Text } = Typography;

const MODES = [
  { label: 'Question', value: 'question' },
  { label: 'Semantic Test', value: 'semantic test' },
  { label: 'Concurrency Test', value: 'concurrency test' },
] as const;

type Mode = (typeof MODES)[number]['value'];

interface Props {
  onSubmit: (result: QueryResponse) => void;
  onConcurrencySubmit?: (results: QueryResponse[]) => void;
}

const QueryForm: React.FC<Props> = ({ onSubmit, onConcurrencySubmit }) => {
  const { refresh: refreshAuth } = useAuth();
  const [mode, setMode] = useState<Mode>('question');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Question mode
  const [question, setQuestion] = useState<string>('');

  // Shared test config
  const [duration, setDuration] = useState<number>(10);
  const [tps, setTps] = useState<number>(30);
  // Concurrency-only config
  const [concurrency, setConcurrency] = useState<number>(5);

  function buildTestQuery(m: Mode): string {
    const uuid = uuidv4();
    return `${m} [tps=${tps} dur=${duration} id=${uuid}]`;
  }

  async function handleSubmit() {
    if (mode === 'question' && !question.trim()) {
      setError('Please enter a question.');
      return;
    }
    setError(null);
    setLoading(true);
    try {
      // Auto-create guest if not logged in, then refresh AuthContext.
      await ensureGuest();
      await refreshAuth();

      if (mode === 'concurrency test') {
        const promises = Array.from({ length: concurrency }, () =>
          submitQuery(buildTestQuery(mode)),
        );
        const results = await Promise.all(promises);
        onConcurrencySubmit?.(results);
      } else if (mode === 'question') {
        const result = await submitQuery(question.trim());
        onSubmit(result);
      } else {
        const result = await submitQuery(buildTestQuery(mode));
        onSubmit(result);
      }
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

        {mode === 'question' && (
          <Form.Item label={<Text strong>Your question</Text>}>
            <Input.TextArea
              rows={3}
              placeholder="e.g. What is the outlook for Apple stock?"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              autoSize={{ minRows: 3, maxRows: 8 }}
            />
          </Form.Item>
        )}

        {mode !== 'question' && (
          <>
            <Form.Item label={<Text strong>Duration (seconds)</Text>}>
              <InputNumber
                min={1}
                max={120}
                value={duration}
                onChange={(v) => setDuration(v ?? 10)}
                style={{ width: 160 }}
              />
            </Form.Item>

            <Form.Item label={<Text strong>Tokens per second</Text>}>
              <InputNumber
                min={1}
                max={500}
                value={tps}
                onChange={(v) => setTps(v ?? 30)}
                style={{ width: 160 }}
              />
            </Form.Item>
          </>
        )}

        {mode === 'concurrency test' && (
          <Form.Item label={<Text strong>Concurrency (number of requests)</Text>}>
            <InputNumber
              min={1}
              max={50}
              value={concurrency}
              onChange={(v) => setConcurrency(v ?? 5)}
              style={{ width: 160 }}
            />
          </Form.Item>
        )}

        {error && (
          <Form.Item>
            <Alert message={error} type="error" showIcon />
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
