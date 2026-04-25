import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Layout, Tag, Typography } from "antd";
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
import { useStyles } from "./App.styles";
import type { NodeGroup, TaskTypeMeta, ThreadSummary } from "./types";

const { Header, Content, Footer } = Layout;
const { Title } = Typography;

export default function App() {
  const styles = useStyles();
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
    perfTestKey,
    startPerfTest,
    exitPerfTest,
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
      <Layout style={styles.layout}>
        <Header
          style={styles.header}
        >
          <div style={styles.headerLeft}>
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
            <Title level={4} style={styles.title}>
              🤖 Fin Agent
            </Title>
            {username && <Tag color="blue" style={styles.tag}>{username}</Tag>}
          </div>
          <Button icon={<FileTextOutlined />} onClick={() => setReportDrawerOpen(true)}>
            Strategy Report
          </Button>
        </Header>

        <Content style={styles.content}>
          {perfTestKey > 0 ? (
            <div style={styles.perfOuter}>
              <div style={styles.perfTopSection}>
                <MessageList messages={messages} onNodeClick={handlePerfNodeClick} />
              </div>

              <div style={styles.perfScrollSection}>
                <StreamingPerfTestPanel
                  key={perfTestKey}
                  userToken={userToken!}
                  taskMeta={taskMeta}
                  onComplete={forcePerfTestComplete}
                />
              </div>
            </div>
          ) : (
            <MessageList
              messages={messages}
              onNodeClick={(n) => {
                // If this node belongs to a perf test message, re-enter the perf grid.
                const msg = [...messages].reverse().find((m) => m.nodes?.some((ng) => ng.node_name === n.node_name));
                if (msg?.isPerfTest) {
                  startPerfTest();
                }
                setDrawerNodeName(n.node_name);
              }}
            />
          )}
        </Content>

        <Footer style={styles.footer}>
          {perfTestKey > 0 ? (
            <div style={styles.footerExit}>
              <Button onClick={exitPerfTest}>
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
