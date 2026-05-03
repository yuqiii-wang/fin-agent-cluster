import { useEffect, useState } from "react";
import { Button, Layout, Tag, Typography } from "antd";
import { HistoryOutlined } from "@ant-design/icons";
import { HistoryPanel } from "./components/HistoryPanel";
import { StreamingPerfTestPanel } from "./components/StreamingPerfTestPanel";
import { fetchActiveThread, fetchHistory } from "./api";
import { useGuestAuth } from "./hooks/useGuestAuth";
import { useStyles } from "./App.styles";
import type { ThreadSummary } from "./types";

const { Header, Content } = Layout;
const { Title } = Typography;

export default function App() {
  const styles = useStyles();
  const { token: userToken, username, loading: authLoading } = useGuestAuth();

  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyItems, setHistoryItems] = useState<ThreadSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  useEffect(() => {
    if (authLoading || !userToken) return;
    fetchHistory(userToken).then(setHistoryItems).catch(console.error);
    fetchActiveThread(userToken).catch(console.error);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authLoading, userToken]);

  return (
    <>
      <Layout style={styles.layout}>
        <Header style={styles.header}>
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
              Stream Runner
            </Title>
            {username && <Tag color="blue" style={styles.tag}>{username}</Tag>}
          </div>
        </Header>

        <Content style={styles.content}>
          {!authLoading && userToken && (
            <StreamingPerfTestPanel userToken={userToken} />
          )}
        </Content>
      </Layout>

      <HistoryPanel
        open={historyOpen}
        items={historyItems}
        onClose={() => setHistoryOpen(false)}
        onRecover={(_thread) => { setHistoryOpen(false); }}
      />
    </>
  );
}
