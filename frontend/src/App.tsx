/**
 * App — root layout.
 *
 * Left panel: thread history list (loaded from backend, persisted per-user).
 * Top-right header: UserButton (login / user menu).
 * Main area: QueryForm or ThreadView depending on selection.
 */

import React, { useCallback, useRef, useState } from 'react';
import { ConfigProvider, Layout, theme, Typography } from 'antd';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { useHistory } from './hooks/useHistory';
import { useCentrifugoPresence } from './hooks/useCentrifugoPresence';
import { useBackgroundSseStatus } from './hooks/useBackgroundSseStatus';
import QueryForm from './components/QueryForm';
import ThreadView from './components/ThreadView';
import ConcurrencyTest from './components/ConcurrencyTest';
import UserButton from './components/UserButton';
import UserHistory from './components/UserHistory';
import type { GraphTopology, QueryResponse, SseInfo, ThreadSummary } from './types';
import { setThreadViewer } from './api/threads';

const { Header, Sider, Content } = Layout;
const { Text } = Typography;

/** Runtime info for threads submitted in this session. */
interface LiveThreadInfo {
  sseInfo: SseInfo | null;
  llmInfo: SseInfo | null;
  topology: GraphTopology | null;
}

/** Headless component: subscribes to a background thread's SSE channel and
 * notifies the parent when the thread-level status changes. Renders nothing. */
const BackgroundSseWatcher: React.FC<{
  threadId: string;
  sseInfo: SseInfo;
  onStatusUpdate: (threadId: string, status: string) => void;
}> = ({ threadId, sseInfo, onStatusUpdate }) => {
  const handleStatus = useCallback(
    (status: string) => onStatusUpdate(threadId, status),
    [threadId, onStatusUpdate],
  );
  useBackgroundSseStatus({ sseInfo, onStatusUpdate: handleStatus });
  return null;
};

const AppInner: React.FC = () => {
  const { user } = useAuth();
  const { history, prepend, reload, updateEntry } = useHistory(user?.id);
  useCentrifugoPresence({ userId: user?.id });

  // Session-local cache of Centrifugo bootstrap tokens, keyed by thread_id.
  const [liveInfo, setLiveInfo] = useState<Record<string, LiveThreadInfo>>({});
  const [activeId, setActiveId] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(true);
  const [concurrencyResults, setConcurrencyResults] = useState<QueryResponse[] | null>(null);
  // True when ThreadView was opened by clicking a row in the concurrency test grid.
  const [fromConcurrency, setFromConcurrency] = useState(false);
  // Preserved last concurrency batch so the grid can be restored on back navigation.
  const lastConcurrencyResultsRef = useRef<QueryResponse[] | null>(null);

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
        topology: result.topology ?? null,
      },
    }));
    setActiveId(result.thread_id);
    setConcurrencyResults(null);
    setFromConcurrency(false);
    setShowForm(false);
  }

  function handleConcurrencySubmit(results: QueryResponse[]) {
    for (const r of results) {
      setLiveInfo((prev) => ({
        ...prev,
        [r.thread_id]: { sseInfo: r.sse ?? null, llmInfo: r.llm ?? null },
      }));
      prepend({
        thread_id: r.thread_id,
        query: r.query ?? r.thread_id,
        status: r.status,
        created_at: r.created_at ?? new Date().toISOString(),
        completed_at: r.completed_at,
        answer: r.answer,
      });
    }
    setActiveId(null);
    setConcurrencyResults(results);
    lastConcurrencyResultsRef.current = results;
    setShowForm(false);
  }

  function handleSelectThread(threadId: string) {
    setActiveId(threadId);
    setFromConcurrency(concurrencyResults !== null);
    setConcurrencyResults(null);
    setShowForm(false);
    // Register viewer flag on the backend so stream_task knows the user is
    // watching this thread (covers running history threads — fire-and-forget).
    setThreadViewer(threadId);
  }

  const activeEntry = history.find((t) => t.thread_id === activeId);
  const activeLive = activeId ? (liveInfo[activeId] ?? null) : null;

  return (
    <Layout style={{ height: '100vh', overflow: 'hidden' }}>
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

      <Layout style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
        <Sider
          width={240}
          style={{
            background: '#0a0a0a',
            borderRight: '1px solid #1f1f1f',
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
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
          {showForm || (!activeEntry && !concurrencyResults) ? (
            <QueryForm onSubmit={handleSubmit} onConcurrencySubmit={handleConcurrencySubmit} />
          ) : concurrencyResults ? (
            <ConcurrencyTest
              initialResults={concurrencyResults}
              onSelectThread={handleSelectThread}
              onStatusUpdate={(threadId, status) => updateEntry(threadId, { status })}
            />
          ) : (
            <ThreadView
              key={activeEntry!.thread_id}
              threadId={activeEntry!.thread_id}
              sseInfo={activeLive?.sseInfo ?? null}
              llmInfo={activeLive?.llmInfo ?? null}
              initialTopology={activeLive?.topology ?? null}
              onDone={reload}
              onStatusChange={(s) => updateEntry(activeEntry!.thread_id, { status: s })}
              onBack={fromConcurrency ? () => {
                setActiveId(null);
                setFromConcurrency(false);
                setConcurrencyResults(lastConcurrencyResultsRef.current);
              } : undefined}
            />
          )}
        </Content>
      </Layout>

      {/* Background SSE watchers — one per non-active session thread that is
          NOT already being watched by ConcurrencyTest's own subscriptions. */}
      {Object.entries(liveInfo)
        .filter(([tid, info]) => {
          if (tid === activeId) return false;
          if (info.sseInfo === null) return false;
          // ConcurrencyTest manages its own per-thread Centrifugo subscriptions;
          // skip creating a duplicate BackgroundSseWatcher for those threads.
          if (concurrencyResults?.some((r) => r.thread_id === tid)) return false;
          return true;
        })
        .map(([tid, info]) => (
          <BackgroundSseWatcher
            key={tid}
            threadId={tid}
            sseInfo={info.sseInfo!}
            onStatusUpdate={(threadId, status) => updateEntry(threadId, { status })}
          />
        ))}
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
