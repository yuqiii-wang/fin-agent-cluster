/**
 * App — root layout.
 *
 * Left panel: thread history list.
 * Main area: QueryForm or ThreadView depending on selection.
 */

import React, { useState } from 'react';
import { Button, ConfigProvider, Layout, theme, Typography } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import QueryForm from './components/QueryForm';
import ThreadView from './components/ThreadView';
import type { QueryResponse, SseInfo } from './types';

const { Header, Sider, Content } = Layout;
const { Text } = Typography;

interface ThreadEntry {
  response: QueryResponse;
  sseInfo: SseInfo | null;
  llmInfo: SseInfo | null;
}

const App: React.FC = () => {
  const [threads, setThreads] = useState<ThreadEntry[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(true);

  function handleSubmit(result: QueryResponse) {
    const entry: ThreadEntry = {
      response: result,
      sseInfo: result.sse ?? null,
      llmInfo: result.llm ?? null,
    };
    setThreads((prev) => [entry, ...prev]);
    setActiveId(result.thread_id);
    setShowForm(false);
  }

  const activeEntry = threads.find((t) => t.response.thread_id === activeId);

  return (
    <ConfigProvider
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: '#1677ff',
          borderRadius: 6,
        },
      }}
    >
      <Layout style={{ minHeight: '100vh' }}>
        <Header
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 16,
            padding: '0 20px',
            background: '#141414',
            borderBottom: '1px solid #1f1f1f',
          }}
        >
          <Text strong style={{ color: '#fff', fontSize: 16 }}>
            Fin Agent
          </Text>
        </Header>

        <Layout>
          <Sider
            width={240}
            style={{
              background: '#0a0a0a',
              borderRight: '1px solid #1f1f1f',
              overflowY: 'auto',
            }}
          >
            <div style={{ padding: '12px 8px' }}>
              <Button
                type="dashed"
                icon={<PlusOutlined />}
                block
                onClick={() => {
                  setActiveId(null);
                  setShowForm(true);
                }}
                style={{ marginBottom: 12 }}
              >
                New Query
              </Button>

              <div>
                {threads.map((entry) => {
                  const isActive = entry.response.thread_id === activeId;
                  return (
                    <div
                      key={entry.response.thread_id}
                      style={{
                        cursor: 'pointer',
                        borderRadius: 6,
                        padding: '6px 8px',
                        marginBottom: 4,
                        background: isActive ? 'rgba(22,119,255,0.15)' : 'transparent',
                      }}
                      onClick={() => {
                        setActiveId(entry.response.thread_id);
                        setShowForm(false);
                      }}
                    >
                      <div>
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
                          {entry.response.query ?? entry.response.thread_id}
                        </Text>
                        <Text style={{ fontSize: 10, color: '#595959' }}>
                          {entry.response.status}
                        </Text>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </Sider>

          <Content
            style={{
              padding: 24,
              overflowY: 'auto',
              background: '#111',
            }}
          >
            {showForm || !activeEntry ? (
              <QueryForm onSubmit={handleSubmit} />
            ) : (
              <ThreadView
                key={activeEntry.response.thread_id}
                threadId={activeEntry.response.thread_id}
                sseInfo={activeEntry.sseInfo}
                llmInfo={activeEntry.llmInfo}
              />
            )}
          </Content>
        </Layout>
      </Layout>
    </ConfigProvider>
  );
};

export default App;
