import { Badge, Drawer, List, Tag, Tooltip, Typography } from "antd";
import { HistoryOutlined } from "@ant-design/icons";
import type { ThreadSummary } from "../types";

const { Text } = Typography;

const STATUS_COLOR: Record<string, string> = {
  completed: "green",
  running: "blue",
  pending: "default",
  failed: "red",
  cancelled: "orange",
};

interface HistoryPanelProps {
  open: boolean;
  items: ThreadSummary[];
  onClose: () => void;
  /** Called when user clicks a history item to recover it. */
  onRecover: (thread: ThreadSummary) => void;
}

/**
 * Side drawer listing the user's previous threads.
 *
 * Completed and running threads are both recoverable — clicking one triggers
 * ``onRecover`` so the parent can reload the thread into the main UI.
 */
export function HistoryPanel({ open, items, onClose, onRecover }: HistoryPanelProps) {
  return (
    <Drawer
      title={
        <span>
          <HistoryOutlined style={{ marginRight: 8 }} />
          Session History
        </span>
      }
      placement="left"
      width={360}
      open={open}
      onClose={onClose}
      styles={{ body: { padding: "8px 0" } }}
    >
      {items.length === 0 ? (
        <div style={{ textAlign: "center", padding: "40px 16px", color: "var(--ant-color-text-secondary)" }}>
          No previous sessions
        </div>
      ) : (
        <List
          dataSource={items}
          renderItem={(item) => (
            <List.Item
              style={{ padding: "10px 16px", cursor: "pointer" }}
              onClick={() => onRecover(item)}
            >
              <List.Item.Meta
                title={
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <Tooltip title={item.query}>
                      <Text
                        style={{ maxWidth: 230, display: "inline-block" }}
                        ellipsis
                        strong
                      >
                        {item.query}
                      </Text>
                    </Tooltip>
                    <Tag color={STATUS_COLOR[item.status] ?? "default"} style={{ flexShrink: 0 }}>
                      {item.status}
                    </Tag>
                  </div>
                }
                description={
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {new Date(item.created_at).toLocaleString()}
                  </Text>
                }
              />
            </List.Item>
          )}
        />
      )}
    </Drawer>
  );
}
