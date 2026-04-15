import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Drawer, Input, Layout, Space, Spin, Typography, theme } from "antd";
import { FileTextOutlined, SearchOutlined } from "@ant-design/icons";
import { ChatInput } from "./components/ChatInput";
import { MessageList } from "./components/MessageList";
import { TaskDrawer } from "./components/TaskDrawer";
import { ReportView } from "./components/ReportView";
import { submitQuery, openStream, cancelQuery, fetchLatestReport, fetchReportById, fetchTaskMeta } from "./api";
import type { ChatMessage, NodeGroup, StrategyReport, TaskInfo, TaskTypeMeta } from "./types";

const { Header, Content, Footer } = Layout;
const { Title } = Typography;

function buildNodeGroups(tasks: TaskInfo[]): NodeGroup[] {
  const map = new Map<string, TaskInfo[]>();
  for (const t of tasks) {
    if (!map.has(t.node_name)) map.set(t.node_name, []);
    map.get(t.node_name)!.push(t);
  }
  return Array.from(map.entries()).map(([node_name, nodeTasks]) => {
    let status: NodeGroup["status"] = "pending";
    if (nodeTasks.some((t) => t.status === "failed")) status = "failed";
    else if (nodeTasks.some((t) => t.status === "running")) status = "running";
    else if (nodeTasks.every((t) => t.status === "completed")) status = "completed";
    else if (nodeTasks.length > 0) status = "running";
    return { node_name, status, tasks: nodeTasks };
  });
}

export default function App() {
  const { token } = theme.useToken();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [drawerNodeName, setDrawerNodeName] = useState<string | null>(null);
  const [tokenStreams, setTokenStreams] = useState<Record<number, string>>({});
  const [taskProviders, setTaskProviders] = useState<Record<number, string>>({});
  const [taskMeta, setTaskMeta] = useState<TaskTypeMeta | null>(null);

  // Fetch task type metadata once on mount for OutputViewer routing
  useEffect(() => {
    fetchTaskMeta().then(setTaskMeta).catch(console.error);
  }, []);

  // ── Strategy report drawer ──
  const [reportDrawerOpen, setReportDrawerOpen] = useState(false);
  const [reportSymbol, setReportSymbol] = useState("");
  const [reportData, setReportData] = useState<StrategyReport | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);

  const handleLoadReport = useCallback(async () => {
    const sym = reportSymbol.trim().toUpperCase();
    if (!sym) return;
    setReportLoading(true);
    setReportError(null);
    setReportData(null);
    try {
      const data = await fetchLatestReport(sym);
      setReportData(data);
    } catch (err) {
      setReportError(err instanceof Error ? err.message : String(err));
    } finally {
      setReportLoading(false);
    }
  }, [reportSymbol]);

  /** Always reflect the latest task data for the open drawer node. */
  const drawerNode = useMemo<NodeGroup | null>(() => {
    if (!drawerNodeName) return null;
    for (let i = messages.length - 1; i >= 0; i--) {
      const node = messages[i].nodes?.find((n) => n.node_name === drawerNodeName);
      if (node) return node;
    }
    return null;
  }, [drawerNodeName, messages]);

  const threadToMsgId = useRef<Map<string, string>>(new Map());
  const cleanupSse = useRef<(() => void) | null>(null);
  const activeThreadId = useRef<string | null>(null);

  const updateMessage = useCallback(
    (msgId: string, patch: Partial<ChatMessage>) => {
      setMessages((prev) =>
        prev.map((m) => (m.id === msgId ? { ...m, ...patch } : m))
      );
    },
    []
  );

  /** Append a single token to the message body (no full-replace needed). */
  const appendMessageText = useCallback((msgId: string, token: string) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === msgId ? { ...m, text: m.text + token } : m))
    );
  }, []);

  const handleSubmit = useCallback(
    async (query: string) => {
      cleanupSse.current?.();
      setTokenStreams({});
      setTaskProviders({});

      const userMsgId = crypto.randomUUID();
      const asstMsgId = crypto.randomUUID();

      setMessages((prev) => [
        ...prev,
        { id: userMsgId, role: "user", text: query },
        // Start with empty text — content arrives via SSE tokens
        { id: asstMsgId, role: "assistant", text: "", status: "running", nodes: [] },
      ]);
      setLoading(true);

      try {
        // POST returns immediately (status="running") — graph runs in background
        const res = await submitQuery(query);
        const threadId = res.thread_id;
        threadToMsgId.current.set(threadId, asstMsgId);
        activeThreadId.current = threadId;
        updateMessage(asstMsgId, { thread_id: threadId });

        const close = openStream(threadId, {
          onStarted: (data) => {
            // Inline task insert — no DB round-trip needed
            const { task_id, node_name, task_key, provider } = data as {
              task_id: number; node_name: string; task_key: string; provider?: string;
            };
            if (provider) {
              setTaskProviders((prev) => ({ ...prev, [task_id]: provider }));
            }
            const newTask: TaskInfo = {
              id: task_id,
              thread_id: threadId,
              node_execution_id: null,
              node_name,
              task_key,
              status: "running",
              input: {},
              output: {},
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            };
            setMessages((prev) =>
              prev.map((m) => {
                if (m.id !== asstMsgId) return m;
                const nodes = m.nodes ?? [];
                const existing = nodes.find((n) => n.node_name === node_name);
                if (existing) {
                  return {
                    ...m,
                    nodes: nodes.map((n) =>
                      n.node_name === node_name
                        ? { ...n, status: "running" as const, tasks: [...n.tasks, newTask] }
                        : n
                    ),
                  };
                }
                return {
                  ...m,
                  nodes: [...nodes, { node_name, status: "running" as const, tasks: [newTask] }],
                };
              })
            );
          },
          onToken: (data) => {
            const { task_id, task_key, data: token } = data as {
              task_id: number;
              task_key: string;
              data: string;
            };
            // llm_analysis tokens → stream into both the main chat bubble and the sidebar
            if (task_key === "llm_analysis") {
              appendMessageText(asstMsgId, token);
            }
            // All tokens → accumulated in sidebar tokenStreams keyed by task_id
            setTokenStreams((prev) => ({
              ...prev,
              [task_id]: (prev[task_id] ?? "") + token,
            }));
          },
          onCompleted: (data) => {
            // Inline task update from SSE payload — avoids extra DB round-trip
            const { task_id, node_name, task_key, output } = data as {
              task_id: number; node_name: string; task_key: string; output: Record<string, unknown>;
            };
            setMessages((prev) =>
              prev.map((m) => {
                if (m.id !== asstMsgId || !m.nodes) return m;
                return {
                  ...m,
                  nodes: m.nodes.map((ng) => {
                    if (ng.node_name !== node_name) return ng;
                    const tasks = ng.tasks.map((t) =>
                      t.id === task_id
                        ? { ...t, status: "completed" as const, output: output || t.output }
                        : t
                    );
                    const allDone = tasks.every((t) => t.status === "completed" || t.status === "failed");
                    return {
                      ...ng,
                      tasks,
                      status: (allDone ? "completed" : ng.status) as NodeGroup["status"],
                    };
                  }),
                };
              })
            );
            // When the decision_maker report is persisted, fetch + attach it to the message
            if (task_key === "db_insert_report" && typeof output?.id === "number") {
              fetchReportById(output.id as number)
                .then((report) => updateMessage(asstMsgId, { report }))
                .catch(console.error);
            }
          },
          onFailed: (data) => {
            const { task_id, node_name, task_key, output } = data as {
              task_id: number; node_name: string; task_key: string; output?: Record<string, unknown>;
            };
            setMessages((prev) =>
              prev.map((m) => {
                if (m.id !== asstMsgId || !m.nodes) return m;
                return {
                  ...m,
                  nodes: m.nodes.map((ng) => {
                    if (ng.node_name !== node_name) return ng;
                    const tasks = ng.tasks.map((t) =>
                      t.id === task_id
                        ? { ...t, status: "failed" as const, output: output || t.output }
                        : t
                    );
                    return { ...ng, tasks, status: "failed" as NodeGroup["status"] };
                  }),
                };
              })
            );
            void task_key;
          },
          onDone: (data) => {
            const { status } = data as { status: string };
            if (status === "cancelled") {
              updateMessage(asstMsgId, { text: "Query cancelled by user.", status: "cancelled" as ChatMessage["status"] });
            } else {
              updateMessage(asstMsgId, { status: status as ChatMessage["status"] });
            }
            activeThreadId.current = null;
            close();
            setLoading(false);
          },
          onClose: () => {
            // SSE disconnected without a done event — mark completed
            updateMessage(asstMsgId, { status: "completed" });
            activeThreadId.current = null;
            setLoading(false);
          },
        });
        cleanupSse.current = close;
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        updateMessage(asstMsgId, { text: `Error: ${msg}`, status: "failed" });
        setLoading(false);
      }
    },
    [updateMessage, appendMessageText]
  );

  const handleCancel = useCallback(async () => {
    const threadId = activeThreadId.current;
    if (!threadId) return;
    try {
      await cancelQuery(threadId);
    } catch {
      // If cancel fails (already done), just close SSE and let UI settle
      cleanupSse.current?.();
      setLoading(false);
    }
  }, []);

  return (
    <>
      <Layout
        style={{
          height: "100vh",
          background: token.colorBgLayout,
          display: "flex",
          flexDirection: "column",
        }}
      >
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
          <Title level={4} style={{ color: token.colorText, margin: 0 }}>
            🤖 Fin Agent
          </Title>
          <Button
            icon={<FileTextOutlined />}
            onClick={() => setReportDrawerOpen(true)}
          >
            Strategy Report
          </Button>
        </Header>

        <Content style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
          <MessageList messages={messages} onNodeClick={(n) => setDrawerNodeName(n.node_name)} />
        </Content>

        <Footer style={{ padding: 0, background: "transparent" }}>
          <ChatInput onSubmit={handleSubmit} onCancel={handleCancel} loading={loading} />
        </Footer>
      </Layout>

      <TaskDrawer node={drawerNode} tokenStreams={tokenStreams} taskProviders={taskProviders} taskMeta={taskMeta} onClose={() => setDrawerNodeName(null)} />

      {/* ── Strategy Report Drawer ── */}
      <Drawer
        title="Strategy Report"
        placement="right"
        width="75vw"
        open={reportDrawerOpen}
        onClose={() => setReportDrawerOpen(false)}
        styles={{ body: { padding: "16px 12px", overflowY: "auto" } }}
      >
        <Space.Compact style={{ width: "100%", marginBottom: 20 }}>
          <Input
            placeholder="Enter ticker symbol, e.g. AAPL"
            value={reportSymbol}
            onChange={(e) => setReportSymbol(e.target.value)}
            onPressEnter={handleLoadReport}
            style={{ textTransform: "uppercase" }}
          />
          <Button
            type="primary"
            icon={<SearchOutlined />}
            onClick={handleLoadReport}
            loading={reportLoading}
          >
            Load
          </Button>
        </Space.Compact>

        {reportLoading && (
          <div style={{ textAlign: "center", padding: "40px 0" }}>
            <Spin size="large" />
          </div>
        )}

        {reportError && !reportLoading && (
          <div style={{ color: token.colorError, padding: "8px 0" }}>
            {reportError}
          </div>
        )}

        {reportData && !reportLoading && (
          <ReportView report={reportData} />
        )}
      </Drawer>
    </>
  );
}
