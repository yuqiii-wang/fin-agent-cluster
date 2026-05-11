/**
 * App — root layout.
 *
 * Left panel: thread history list (loaded from backend, persisted per-user).
 * Top-right header: UserButton (login / user menu).
 * Main area: QueryForm or ThreadView depending on selection.
 */

import React, { useState } from 'react';
import { ConfigProvider, Layout, theme, Typography } from 'antd';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { useHistory } from './hooks/useHistory';
import QueryForm from './components/QueryForm';
import ThreadView from './components/ThreadView';
import UserButton from './components/UserButton';
import UserHistory from './components/UserHistory';
import type { QueryResponse, SseInfo, ThreadSummary } from './types';

const { Header, Sider, Content } = Layout;
const { Text } = Typography;

/** Runtime info for threads submitted in this session. */
interface LiveThreadInfo {
  sseInfo: SseInfo | null;
  llmInfo: SseInfo | null;
}

const AppInner: React.FC = () => {
  const { user } = useAuth();
  const { history, prepend, reload } = useHistory(user?.id);

  // Session-local cache of Centrifugo bootstrap tokens, keyed by thread_id.
  const [liveInfo, setLiveInfo] = useState<Record<string, LiveThreadInfo>>({});
  const [activeId, setActiveId] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(true);

  function handleSubmit(result: QueryResponse) {
    const summary: ThreadSummary = {
      thread_id: result.thread_id,
      query: result.query ?? result.thread_id,
      status: result.status,
      created_at: result.created_at ?? new Date().toISOString(),
      completed_at: result.completed_at,
      answer: result.answer,
    };
    prepend(summary);
    setLiveInfo((prev) => ({
      ...prev,
      [result.thread_id]: {
        sseInfo: result.sse ?? null,
        llmInfo: result.llm ?? null,
      },
    }));
    setActiveId(result.thread_id);
    setShowForm(false);
  }

  function handleSelectThread(threadId: string) {
    setActiveId(threadId);
    setShowForm(false);
  }

  const activeEntry = history.find((t) => t.thread_id === activeId);
  const activeLive = activeId ? (liveInfo[activeId] ?? null) : null;

  return (
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
        <Text strong style={{ color: '#fff', fontSize: 16, flex: 1 }}>
          Fin Agent
        </Text>
        <UserButton />
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
          <UserHistory
            history={history}
            activeId={activeId}
            isAuthenticated={!!user}
            onSelect={handleSelectThread}
            onNewQuery={() => {
              setActiveId(null);
              setShowForm(true);
            }}
          />
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
              key={activeEntry.thread_id}
              threadId={activeEntry.thread_id}
              sseInfo={activeLive?.sseInfo ?? null}
              llmInfo={activeLive?.llmInfo ?? null}
              onDone={reload}
            />
          )}
        </Content>
      </Layout>
    </Layout>
  );
};

const App: React.FC = () => (
  <ConfigProvider
    theme={{
      algorithm: theme.darkAlgorithm,
      token: {
        colorPrimary: '#1677ff',
        borderRadius: 6,
      },
    }}
  >
    <AuthProvider>
      <AppInner />
    </AuthProvider>
  </ConfigProvider>
);

export default App;
