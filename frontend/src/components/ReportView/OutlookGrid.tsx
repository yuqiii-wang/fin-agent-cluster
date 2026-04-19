import { Card, Col, Row, Space, Typography } from "antd";
import { ArrowUpOutlined, ArrowDownOutlined } from "@ant-design/icons";
import { MdSection } from "./MdSection";

const { Text } = Typography;

interface OutlookGridProps {
  symbol: string;
  riseToday: string | null;
  riseTomorrow: string | null;
  riseShortTerm: string | null;
  riseLongTerm: string | null;
  fallToday: string | null;
  fallTomorrow: string | null;
  fallShortTerm: string | null;
  fallLongTerm: string | null;
}

export function OutlookGrid({
  symbol,
  riseToday,
  riseTomorrow,
  riseShortTerm,
  riseLongTerm,
  fallToday,
  fallTomorrow,
  fallShortTerm,
  fallLongTerm,
}: OutlookGridProps) {
  const riseItems = [
    { label: "Today",      content: riseToday },
    { label: "Tomorrow",   content: riseTomorrow },
    { label: "1–2 Weeks",  content: riseShortTerm },
    { label: "6+ Months",  content: riseLongTerm },
  ];
  const fallItems = [
    { label: "Today",      content: fallToday },
    { label: "Tomorrow",   content: fallTomorrow },
    { label: "1–2 Weeks",  content: fallShortTerm },
    { label: "6+ Months",  content: fallLongTerm },
  ];

  return (
    <Row gutter={[12, 0]}>
      <Col span={12}>
        <Card
          size="small"
          title={
            <Space size={6}>
              <ArrowUpOutlined style={{ color: "#52c41a" }} />
              <Text strong style={{ fontSize: 14, color: "#52c41a" }}>
                Rise Scenarios — {symbol}
              </Text>
            </Space>
          }
          styles={{ header: { background: "#f6ffed" }, body: { padding: "10px 14px" } }}
        >
          {riseItems.map(({ label, content }) => (
            <div key={label} style={{ marginBottom: 10 }}>
              <Text strong style={{ fontSize: 12 }}>{label}</Text>
              <div style={{ marginTop: 4 }}>
                <MdSection content={content} />
              </div>
            </div>
          ))}
        </Card>
      </Col>
      <Col span={12}>
        <Card
          size="small"
          title={
            <Space size={6}>
              <ArrowDownOutlined style={{ color: "#ff4d4f" }} />
              <Text strong style={{ fontSize: 14, color: "#ff4d4f" }}>
                Fall Scenarios — {symbol}
              </Text>
            </Space>
          }
          styles={{ header: { background: "#fff2f0" }, body: { padding: "10px 14px" } }}
        >
          {fallItems.map(({ label, content }) => (
            <div key={label} style={{ marginBottom: 10 }}>
              <Text strong style={{ fontSize: 12 }}>{label}</Text>
              <div style={{ marginTop: 4 }}>
                <MdSection content={content} />
              </div>
            </div>
          ))}
        </Card>
      </Col>
    </Row>
  );
}
