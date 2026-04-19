import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Layout, Tag, Typography, theme } from "antd";
import { FileTextOutlined, HistoryOutlined } from "@ant-design/icons";
import { ChatInput } from "./components/ChatInput";
import { HistoryPanel } from "./components/HistoryPanel";
import { MessageList } from "./components/MessageList";
import { StreamingPerfTestPanel } from "./components/StreamingPerfTestPanel";
import { TaskDrawer } from "./components/TaskDrawer";
import { fetchActiveThread, fetchHistory, fetchTaskMeta } from "./api";
import { useGuestAuth } from "./hooks/useGuestAuth";
import { useStreamSession } from "./app/useStreamSession";
import { ReportDrawerPanel } from "./app/ReportDrawerPanel";
import type { NodeGroup, TaskTypeMeta, ThreadSummary } from "./types";

const { Header, Content, Footer } = Layout;
const { Title } = Typography;

export default function App() {
  const { token } = theme.useToken();
  const { token: userToken, username } = useGuestAuth();

  const [drawerNodeName, setDrawerNodeName] = useState<string | null>(null);
  const [taskMeta, setTaskMeta] = useState<TaskTypeMeta | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyItems, setHistoryItems] = useState<ThreadSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [reportDrawerOpen, setReportDrawerOpen] = useState(false);

  const {
    messages,
    loading,
    tokenStreams,
    taskProviders,
    perfTestThreadId,
    setPerfTestThreadId,
    perfTestGridVisible,
    setPerfTestGridVisible,
    forcePerfTestComplete,
    recoverThread,
    handleSubmit,
    handleCancel,
  } = useStreamSession(userToken, setHistoryItems);

  useEffect(() => {
    fetchTaskMeta().then(setTaskMeta).catch(console.error);
  }, []);

  const drawerNode = useMemo<NodeGroup | null>(() => {
    if (!drawerNodeName) return null;
    for (let i = messages.length - 1; i >= 0; i--) {
      const node = messages[i].nodes?.find((n) => n.node_name === drawerNodeName);
      if (node) return node;
    }
    return null;
  }, [drawerNodeName, messages]);

  useEffect(() => {
    if (!userToken) return;
    fetchActiveThread(userToken).then((active) => {
      if (active) recoverThread(active);
    }).catch(console.error);
    fetchHistory(userToken).then(setHistoryItems).catch(console.error);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userToken]);

  const handlePerfNodeClick = useCallback((n: NodeGroup) => {
    setDrawerNodeName(n.node_name);
  }, []);

  return (
    <>
      <Layout style={{ height: "100vh", background: token.colorBgLayout, display: "flex", flexDirection: "column" }}>
        <Header
          style={{
            background: token.colorBgContainer,
            borderBottom: `1px solid ${token.colorBorder}`,
            padding: "0 20px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <Button
              icon={<HistoryOutlined />}
              loading={historyLoading}
              onClick={() => {
                setHistoryOpen(true);
                if (userToken) {
                  setHistoryLoading(true);
                  fetchHistory(userToken)
                    .then(setHistoryItems)
                    .catch(console.error)
                    .finally(() => setHistoryLoading(false));
                }
              }}
            />
            <Title level={4} style={{ color: token.colorText, margin: 0 }}>
              🤖 Fin Agent
            </Title>
            {username && <Tag color="blue" style={{ margin: 0 }}>{username}</Tag>}
          </div>
          <Button icon={<FileTextOutlined />} onClick={() => setReportDrawerOpen(true)}>
            Strategy Report
          </Button>
        </Header>

        <Content style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
          {perfTestThreadId ? (
            <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
              <div style={{ flex: "0 0 auto" }}>
                <MessageList messages={messages} onNodeClick={handlePerfNodeClick} />
              </div>

              <div style={{ flex: 1, overflowY: "auto", padding: "0 20px 16px" }}>
                <StreamingPerfTestPanel
                  key={perfTestThreadId}
                  initialThreadId={perfTestThreadId}
                  userToken={userToken!}
                  onComplete={forcePerfTestComplete}
                />
              </div>
            </div>
          ) : (
            <MessageList
              messages={messages}
              onNodeClick={(n) => {
                // If this node belongs to a perf test message, re-enter the perf grid first
                const msg = [...messages].reverse().find((m) => m.nodes?.some((ng) => ng.node_name === n.node_name));
                if (msg?.isPerfTest && msg.thread_id) {
                  setPerfTestThreadId(msg.thread_id);
                }
                setDrawerNodeName(n.node_name);
              }}
            />
          )}
        </Content>

        <Footer style={{ padding: 0, background: "transparent" }}>
          {perfTestThreadId ? (
            <div style={{ padding: "8px 20px", display: "flex", justifyContent: "flex-end" }}>
              <Button onClick={() => { setPerfTestThreadId(null); setPerfTestGridVisible(true); }}>
                Exit Performance Test
              </Button>
            </div>
          ) : (
            <ChatInput onSubmit={handleSubmit} onCancel={handleCancel} loading={loading} />
          )}
        </Footer>
      </Layout>

      <TaskDrawer
        node={drawerNode}
        tokenStreams={tokenStreams}
        taskProviders={taskProviders}
        taskMeta={taskMeta}
        onClose={() => setDrawerNodeName(null)}
      />

      <HistoryPanel
        open={historyOpen}
        items={historyItems}
        onClose={() => setHistoryOpen(false)}
        onRecover={(thread) => { recoverThread(thread); setHistoryOpen(false); }}
      />

      <ReportDrawerPanel open={reportDrawerOpen} onClose={() => setReportDrawerOpen(false)} />
    </>
  );
}
