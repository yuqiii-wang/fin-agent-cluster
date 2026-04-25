import { Card, Col, Row, Space, Typography } from "antd";
import { ArrowUpOutlined, ArrowDownOutlined } from "@ant-design/icons";
import { MdSection } from "./MdSection";
import { useStyles } from "./OutlookGrid.styles";

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
  const styles = useStyles();
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
              <ArrowUpOutlined style={styles.riseIcon} />
              <Text strong style={styles.riseText}>
                Rise Scenarios — {symbol}
              </Text>
            </Space>
          }
          styles={styles.riseCardHeader}
        >
          {riseItems.map(({ label, content }) => (
            <div key={label} style={styles.item}>
              <Text strong style={styles.itemLabel}>{label}</Text>
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
              <ArrowDownOutlined style={styles.fallIcon} />
              <Text strong style={styles.fallText}>
                Fall Scenarios — {symbol}
              </Text>
            </Space>
          }
          styles={styles.fallCardHeader}
        >
          {fallItems.map(({ label, content }) => (
            <div key={label} style={styles.item}>
              <Text strong style={styles.itemLabel}>{label}</Text>
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
