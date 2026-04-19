import {
  Col,
  Divider,
  Row,
  Space,
  Tag,
  Tooltip,
  Typography,
  theme,
} from "antd";
import {
  ArrowUpOutlined,
  ArrowDownOutlined,
  ExclamationCircleOutlined,
  InfoCircleOutlined,
  LineChartOutlined,
  NodeIndexOutlined,
  RadarChartOutlined,
  RiseOutlined,
} from "@ant-design/icons";
import type { CSSProperties } from "react";
import type { StrategyReport } from "../../types";
import { SectionCard } from "./SectionCard";
import { OutlookGrid } from "./OutlookGrid";
import { ReferencesSection } from "./ReferencesSection";

const { Title, Text } = Typography;

interface Props {
  report: StrategyReport;
}

export function ReportView({ report }: Props) {
  const { token } = theme.useToken();

  const headerStyle: CSSProperties = {
    marginBottom: 20,
    paddingBottom: 12,
    borderBottom: `1px solid ${token.colorBorder}`,
  };

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", padding: "16px 8px" }}>
      <div style={headerStyle}>
        <Space align="baseline" size={12}>
          <Title level={3} style={{ margin: 0 }}>{report.symbol}</Title>
          <Text type="secondary" style={{ fontSize: 13 }}>
            Report #{report.id} — {new Date(report.created_at).toLocaleString()}
          </Text>
        </Space>
      </div>

      <Title level={4}>
        <RadarChartOutlined style={{ marginRight: 8 }} />
        Technical Analysis
      </Title>

      <Row gutter={[12, 0]}>
        <Col span={12}>
          <SectionCard
            title="Short-term Technical (1–2 weeks)"
            icon={<LineChartOutlined />}
            content={report.short_term_technical_desc}
          />
        </Col>
        <Col span={12}>
          <SectionCard
            title="Long-term Technical (6+ months)"
            icon={<LineChartOutlined />}
            content={report.long_term_technical_desc}
          />
        </Col>
      </Row>

      <Divider style={{ margin: "12px 0" }} />

      <Title level={4}>
        <InfoCircleOutlined style={{ marginRight: 8 }} />
        Fundamentals &amp; Market Context
      </Title>

      <SectionCard title="News &amp; Sentiment" icon={<NodeIndexOutlined />} content={report.news_desc} />
      <SectionCard title="Business Overview" icon={<InfoCircleOutlined />} content={report.basic_biz_desc} />
      <SectionCard title="Industry Dynamics" icon={<RadarChartOutlined />} content={report.industry_desc} />
      <SectionCard
        title="Significant Events (Earnings / M&A / Product)"
        icon={<ExclamationCircleOutlined />}
        content={report.significant_event_desc}
        extra={
          !report.significant_event_desc ? (
            <Tag color="default" style={{ fontStyle: "italic", opacity: 0.6, marginRight: 0 }}>
              Data absent
            </Tag>
          ) : null
        }
      />

      <Divider style={{ margin: "12px 0" }} />

      <Title level={4}>
        <RiseOutlined style={{ marginRight: 8 }} />
        Risk &amp; Growth
      </Title>

      <Row gutter={[12, 0]}>
        <Col span={12}>
          <SectionCard title="Short-term Risks (1–2 weeks)" icon={<ArrowDownOutlined style={{ color: "#ff4d4f" }} />} content={report.short_term_risk_desc} />
        </Col>
        <Col span={12}>
          <SectionCard title="Long-term Risks (6+ months)" icon={<ArrowDownOutlined style={{ color: "#ff4d4f" }} />} content={report.long_term_risk_desc} />
        </Col>
      </Row>

      <Row gutter={[12, 0]}>
        <Col span={12}>
          <SectionCard title="Short-term Growth Catalysts" icon={<ArrowUpOutlined style={{ color: "#52c41a" }} />} content={report.short_term_growth_desc} />
        </Col>
        <Col span={12}>
          <SectionCard title="Long-term Growth Catalysts" icon={<ArrowUpOutlined style={{ color: "#52c41a" }} />} content={report.long_term_growth_desc} />
        </Col>
      </Row>

      <SectionCard
        title="Recent Trade Anomalies"
        icon={<ExclamationCircleOutlined style={{ color: "#faad14" }} />}
        content={report.recent_trade_anomalies}
        extra={
          !report.recent_trade_anomalies ? (
            <Tag color="default" style={{ fontStyle: "italic", opacity: 0.6, marginRight: 0 }}>
              Data absent
            </Tag>
          ) : null
        }
      />

      <Divider style={{ margin: "12px 0" }} />

      <Title level={4}>
        <Tooltip title="Directional outlook scenarios for different time horizons">
          Price Outlook Scenarios
        </Tooltip>
      </Title>

      <OutlookGrid
        symbol={report.symbol}
        riseToday={report.likely_today_rise_desc}
        riseTomorrow={report.likely_tom_rise_desc}
        riseShortTerm={report.likely_short_term_rise_desc}
        riseLongTerm={report.likely_long_term_rise_desc}
        fallToday={report.likely_today_fall_desc}
        fallTomorrow={report.likely_tom_fall_desc}
        fallShortTerm={report.likely_short_term_fall_desc}
        fallLongTerm={report.likely_long_term_fall_desc}
      />

      <Divider style={{ margin: "20px 0 12px" }} />

      <Title level={4}>
        <NodeIndexOutlined style={{ marginRight: 8 }} />
        References
      </Title>
      <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 12 }}>
        {report.reference_tasks.length} task
        {report.reference_tasks.length !== 1 ? "s" : ""} referenced by this report.
      </Text>

      <ReferencesSection tasks={report.reference_tasks} symbol={report.symbol} />
    </div>
  );
}
