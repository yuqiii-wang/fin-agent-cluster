import { Alert, Collapse, Space, Tag, Typography, theme } from "antd";
import { LineChartOutlined, NodeIndexOutlined } from "@ant-design/icons";
import type { TaskInfo } from "../../types";
import { isQuantKey, isTextKey, taskLabel } from "./helpers";
import { OhlcvReferenceItem } from "./OhlcvReferenceItem";
import { NewsReferenceItem } from "./NewsReferenceItem";

const { Text, Title: TypoTitle } = Typography;

export function ReferencesSection({ tasks, symbol }: { tasks: TaskInfo[]; symbol: string }) {
  const { token } = theme.useToken();

  if (tasks.length === 0) {
    return (
      <Alert
        type="info"
        message="No reference tasks were recorded for this report."
        style={{ marginTop: 8 }}
      />
    );
  }

  const quantTasks = tasks.filter((t) => isQuantKey(t.task_key));
  const textTasks  = tasks.filter((t) => isTextKey(t.task_key));

  const ohlcvItems = quantTasks.map((t) => ({
    key: String(t.id),
    label: (
      <Space size={8}>
        <LineChartOutlined />
        <Text strong style={{ fontSize: 13 }}>{taskLabel(t.task_key)}</Text>
        <Tag color="blue" style={{ fontSize: 11 }}>task #{t.id}</Tag>
      </Space>
    ),
    children: <OhlcvReferenceItem task={t} symbol={symbol} />,
  }));

  const newsItems = textTasks.map((t) => ({
    key: String(t.id),
    label: (
      <Space size={8}>
        <NodeIndexOutlined />
        <Text strong style={{ fontSize: 13 }}>{taskLabel(t.task_key)}</Text>
        <Tag color="geekblue" style={{ fontSize: 11 }}>task #{t.id}</Tag>
      </Space>
    ),
    children: <NewsReferenceItem task={t} />,
  }));

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      {ohlcvItems.length > 0 && (
        <div>
          <TypoTitle level={5} style={{ marginBottom: 8 }}>
            <LineChartOutlined style={{ marginRight: 6 }} />
            Quant Charts
          </TypoTitle>
          <Collapse
            items={ohlcvItems}
            defaultActiveKey={ohlcvItems.slice(0, 1).map((i) => i.key)}
            style={{ background: token.colorBgContainer }}
          />
        </div>
      )}
      {newsItems.length > 0 && (
        <div>
          <TypoTitle level={5} style={{ marginBottom: 8 }}>
            <NodeIndexOutlined style={{ marginRight: 6 }} />
            News &amp; Macro Data
          </TypoTitle>
          <Collapse
            items={newsItems}
            defaultActiveKey={[]}
            style={{ background: token.colorBgContainer }}
          />
        </div>
      )}
    </Space>
  );
}
