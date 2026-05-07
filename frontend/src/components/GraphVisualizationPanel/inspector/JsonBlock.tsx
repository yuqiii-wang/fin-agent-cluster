import { Typography } from "antd";

const { Text } = Typography;

export function JsonBlock({ value }: { value: unknown }) {
  const text = JSON.stringify(value, null, 2);
  if (!text || text === "{}" || text === "null") {
    return <Text type="secondary" style={{ fontSize: 12 }}>—</Text>;
  }
  return (
    <pre
      style={{
        fontSize: 11,
        background: "var(--ant-color-bg-layout)",
        border: "1px solid var(--ant-color-border)",
        borderRadius: 6,
        padding: "8px 10px",
        overflowX: "auto",
        maxHeight: 260,
        overflowY: "auto",
        margin: 0,
        whiteSpace: "pre-wrap",
        wordBreak: "break-all",
      }}
    >
      {text}
    </pre>
  );
}
