import { Badge, Drawer, List, Tag, Tooltip, Typography } from "antd";
import { HistoryOutlined } from "@ant-design/icons";
import type { ThreadSummary } from "../types";
import { useStyles } from "./HistoryPanel.styles";

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
  const styles = useStyles();
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
        <div style={styles.emptyState}>
          No previous sessions
        </div>
      ) : (
        <List
          dataSource={items}
          renderItem={(item) => (
            <List.Item
              style={styles.listItem}
              onClick={() => onRecover(item)}
            >
              <List.Item.Meta
                title={
                  <div style={styles.titleRow}>
                    <Tooltip title={item.query}>
                      <Text
                        style={styles.titleText}
                        ellipsis
                        strong
                      >
                        {item.query}
                      </Text>
                    </Tooltip>
                    <Tag color={STATUS_COLOR[item.status] ?? "default"} style={styles.titleTag}>
                      {item.status}
                    </Tag>
                  </div>
                }
                description={
                  <Text type="secondary" style={styles.timeText}>
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
