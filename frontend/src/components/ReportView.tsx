import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Alert,
  Card,
  Col,
  Collapse,
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
import type { StrategyReport, TaskInfo } from "../types";
import { CandlestickChart, type OHLCVBar } from "./CandlestickChart";

const { Title, Text, Paragraph } = Typography;

// ── Task type helpers — derived from key suffix, no hardcoded lists ──────────
const isQuantKey = (taskKey: string): boolean => taskKey.endsWith(".quant");
const isTextKey  = (taskKey: string): boolean => taskKey.endsWith(".text");

// ── Helpers ──────────────────────────────────────────────────────────────────

function taskLabel(taskKey: string): string {
  const map: Record<string, string> = {
    "market_data_collector.ohlcv.15min.quant":        "OHLCV 15-min (7 days)",
    "market_data_collector.ohlcv.1h.quant":           "OHLCV 1-hour (30 days)",
    "market_data_collector.ohlcv.1day.quant":         "OHLCV Daily (1 year)",
    "market_data_collector.ohlcv.1mo.quant":          "OHLCV Monthly (10 years)",
    "market_data_collector.ohlcv.futures_1mo.quant":  "Futures 1-month",
    "market_data_collector.ohlcv.futures_6mo.quant":  "Futures 6-month",
    "market_data_collector.ohlcv.options_1mo.quant":  "Options 1-month",
    "market_data_collector.ohlcv.options_6mo.quant":  "Options 6-month",
    "market_data_collector.us_treasury.quant":        "US Treasury Yields",
    "market_data_collector.web_search.company.text":  "Company News",
    "query_optimizer.comprehend_basics.text":         "Query Analysis",
    "query_optimizer.validate_basics.text":           "Validate Basics",
    "query_optimizer.populate_json.text":             "Populate Output",
    "decision_maker.llm_infer.text":                  "Decision Inference",
    "decision_maker.db_insert_report.text":           "Save Report",
  };
  // Fallback: strip trailing .quant/.text suffix then use last segment
  const withoutSuffix = taskKey.replace(/\.(quant|text)$/, "");
  const segment = withoutSuffix.split(".").pop() ?? taskKey;
  return map[taskKey] ?? segment.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// ── Sentinel for absent data ─────────────────────────────────────────────────
const ABSENT_TAG = (
  <Tag color="default" style={{ fontStyle: "italic", opacity: 0.6 }}>
    Data absent
  </Tag>
);

function sentimentColor(level: string | undefined): string {
  if (!level) return "default";
  const l = level.toLowerCase();
  if (l === "positive" || l === "bullish") return "success";
  if (l === "negative" || l === "bearish") return "error";
  if (l === "neutral") return "default";
  return "processing";
}

// ── Markdown renderer ────────────────────────────────────────────────────────

interface MdProps {
  content: string | null | undefined;
  monoBg?: string;
}

function MdSection({ content, monoBg }: MdProps) {
  const { token } = theme.useToken();
  const bg = monoBg ?? token.colorBgLayout;

  if (!content) return ABSENT_TAG;

  const proseStyle: CSSProperties = {
    fontSize: 14,
    lineHeight: 1.75,
    color: token.colorText,
  };

  return (
    <div style={proseStyle}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          img: ({ src, alt }) => (
            <img
              src={src}
              alt={alt}
              style={{
                maxWidth: "100%",
                borderRadius: token.borderRadius,
                margin: "8px 0",
                border: `1px solid ${token.colorBorder}`,
              }}
            />
          ),
          code: ({ children, className }) => {
            const isBlock = className?.startsWith("language-");
            return isBlock ? (
              <pre
                style={{
                  background: bg,
                  border: `1px solid ${token.colorBorder}`,
                  borderRadius: token.borderRadius,
                  padding: "10px 14px",
                  overflowX: "auto",
                  fontSize: 12,
                  fontFamily: "'Courier New', monospace",
                }}
              >
                <code>{children}</code>
              </pre>
            ) : (
              <code
                style={{
                  background: bg,
                  padding: "1px 4px",
                  borderRadius: 3,
                  fontSize: "0.9em",
                  fontFamily: "'Courier New', monospace",
                }}
              >
                {children}
              </code>
            );
          },
          table: ({ children }) => (
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                marginBottom: 8,
                fontSize: 13,
              }}
            >
              {children}
            </table>
          ),
          th: ({ children }) => (
            <th
              style={{
                border: `1px solid ${token.colorBorder}`,
                padding: "6px 10px",
                background: token.colorBgLayout,
                textAlign: "left",
              }}
            >
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td
              style={{
                border: `1px solid ${token.colorBorder}`,
                padding: "5px 10px",
              }}
            >
              {children}
            </td>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

// ── Section card ─────────────────────────────────────────────────────────────

interface SectionCardProps {
  title: string;
  icon?: React.ReactNode;
  content: string | null | undefined;
  extra?: React.ReactNode;
}

function SectionCard({ title, icon, content, extra }: SectionCardProps) {
  const { token } = theme.useToken();
  return (
    <Card
      size="small"
      title={
        <Space size={6}>
          {icon}
          <Text strong style={{ fontSize: 14 }}>
            {title}
          </Text>
        </Space>
      }
      extra={extra}
      styles={{
        body: {
          padding: "12px 16px",
          background: token.colorBgContainer,
        },
        header: { background: token.colorBgLayout },
      }}
      style={{ marginBottom: 12 }}
    >
      <MdSection content={content} />
    </Card>
  );
}

// ── Rise / Fall outlook grid ──────────────────────────────────────────────────

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

function OutlookGrid({
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
    { label: "Today", content: riseToday },
    { label: "Tomorrow", content: riseTomorrow },
    { label: "1–2 Weeks", content: riseShortTerm },
    { label: "6+ Months", content: riseLongTerm },
  ];
  const fallItems = [
    { label: "Today", content: fallToday },
    { label: "Tomorrow", content: fallTomorrow },
    { label: "1–2 Weeks", content: fallShortTerm },
    { label: "6+ Months", content: fallLongTerm },
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
              <Text strong style={{ fontSize: 12 }}>
                {label}
              </Text>
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
              <Text strong style={{ fontSize: 12 }}>
                {label}
              </Text>
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

// ── References — News task ────────────────────────────────────────────────────

interface NewsArticle {
  title?: string;
  published_at?: string;
  source_name?: string;
  ai_summary?: string;
  sentiment_level?: string;
  sector?: string;
  topic_level1?: string;
  url?: string;
}

function NewsReferenceItem({ task }: { task: TaskInfo }) {
  const { token } = theme.useToken();
  const output = task.output as Record<string, unknown>;

  // The output may carry a list under `articles`, `news`, `items`, or similar
  const rawList: unknown =
    output?.articles ?? output?.news ?? output?.items ?? output?.results ?? null;
  const articles: NewsArticle[] = Array.isArray(rawList)
    ? (rawList as NewsArticle[])
    : output
      ? [output as NewsArticle] // single article object
      : [];

  if (articles.length === 0) {
    return (
      <Paragraph style={{ fontSize: 13, color: token.colorTextSecondary }}>
        {JSON.stringify(output, null, 2)}
      </Paragraph>
    );
  }

  return (
    <Space direction="vertical" size={8} style={{ width: "100%" }}>
      {articles.slice(0, 20).map((a, idx) => (
        <Card
          key={idx}
          size="small"
          styles={{ body: { padding: "8px 12px" } }}
          style={{ background: token.colorBgLayout }}
        >
          <Space direction="vertical" size={2} style={{ width: "100%" }}>
            <Space size={6} wrap>
              {a.sentiment_level && (
                <Tag color={sentimentColor(a.sentiment_level)} style={{ fontSize: 11 }}>
                  {a.sentiment_level}
                </Tag>
              )}
              {a.sector && (
                <Tag color="blue" style={{ fontSize: 11 }}>
                  {a.sector}
                </Tag>
              )}
              {a.topic_level1 && (
                <Tag style={{ fontSize: 11 }}>{a.topic_level1}</Tag>
              )}
              {a.published_at && (
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {new Date(a.published_at).toLocaleString()}
                </Text>
              )}
            </Space>
            {a.title && (
              <Text strong style={{ fontSize: 13 }}>
                {a.url ? (
                  <a href={a.url} target="_blank" rel="noopener noreferrer">
                    {a.title}
                  </a>
                ) : (
                  a.title
                )}
              </Text>
            )}
            {a.ai_summary && (
              <Paragraph
                style={{ fontSize: 12, marginBottom: 0, color: token.colorTextSecondary }}
              >
                {a.ai_summary}
              </Paragraph>
            )}
          </Space>
        </Card>
      ))}
    </Space>
  );
}

// ── References — OHLCV chart task ─────────────────────────────────────────────

function OhlcvReferenceItem({ task, symbol }: { task: TaskInfo; symbol: string }) {
  const output = task.output as Record<string, unknown>;

  // normalise: bars may live under `bars`, `ohlcv`, `data`, or directly as an array
  const rawBars: unknown =
    output?.bars ?? output?.ohlcv ?? output?.data ?? (Array.isArray(output) ? output : null);
  const bars: OHLCVBar[] = Array.isArray(rawBars) ? (rawBars as OHLCVBar[]) : [];

  if (bars.length === 0) {
    return (
      <Alert
        type="warning"
        message="No OHLCV bars in task output"
        style={{ marginBottom: 12 }}
      />
    );
  }

  return (
    <CandlestickChart bars={bars} symbol={symbol} taskKey={task.task_key} height={300} />
  );
}

// ── References section ────────────────────────────────────────────────────────

function ReferencesSection({ tasks, symbol }: { tasks: TaskInfo[]; symbol: string }) {
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
        <Text strong style={{ fontSize: 13 }}>
          {taskLabel(t.task_key)}
        </Text>
        <Tag color="blue" style={{ fontSize: 11 }}>
          task #{t.id}
        </Tag>
      </Space>
    ),
    children: <OhlcvReferenceItem task={t} symbol={symbol} />,
  }));

  const newsItems = textTasks.map((t) => ({
    key: String(t.id),
    label: (
      <Space size={8}>
        <NodeIndexOutlined />
        <Text strong style={{ fontSize: 13 }}>
          {taskLabel(t.task_key)}
        </Text>
        <Tag color="geekblue" style={{ fontSize: 11 }}>
          task #{t.id}
        </Tag>
      </Space>
    ),
    children: <NewsReferenceItem task={t} />,
  }));

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      {ohlcvItems.length > 0 && (
        <div>
          <Title level={5} style={{ marginBottom: 8 }}>
            <LineChartOutlined style={{ marginRight: 6 }} />
            Quant Charts
          </Title>
          <Collapse
            items={ohlcvItems}
            defaultActiveKey={ohlcvItems.slice(0, 1).map((i) => i.key)}
            style={{ background: token.colorBgContainer }}
          />
        </div>
      )}
      {newsItems.length > 0 && (
        <div>
          <Title level={5} style={{ marginBottom: 8 }}>
            <NodeIndexOutlined style={{ marginRight: 6 }} />
            News &amp; Macro Data
          </Title>
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

// ── Main component ────────────────────────────────────────────────────────────

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
      {/* ── Header ── */}
      <div style={headerStyle}>
        <Space align="baseline" size={12}>
          <Title level={3} style={{ margin: 0 }}>
            {report.symbol}
          </Title>
          <Text type="secondary" style={{ fontSize: 13 }}>
            Report #{report.id} — {new Date(report.created_at).toLocaleString()}
          </Text>
        </Space>
      </div>

      {/* ── Core Analysis ── */}
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

      <SectionCard
        title="News &amp; Sentiment"
        icon={<NodeIndexOutlined />}
        content={report.news_desc}
      />
      <SectionCard
        title="Business Overview"
        icon={<InfoCircleOutlined />}
        content={report.basic_biz_desc}
      />
      <SectionCard
        title="Industry Dynamics"
        icon={<RadarChartOutlined />}
        content={report.industry_desc}
      />
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
          <SectionCard
            title="Short-term Risks (1–2 weeks)"
            icon={<ArrowDownOutlined style={{ color: "#ff4d4f" }} />}
            content={report.short_term_risk_desc}
          />
        </Col>
        <Col span={12}>
          <SectionCard
            title="Long-term Risks (6+ months)"
            icon={<ArrowDownOutlined style={{ color: "#ff4d4f" }} />}
            content={report.long_term_risk_desc}
          />
        </Col>
      </Row>

      <Row gutter={[12, 0]}>
        <Col span={12}>
          <SectionCard
            title="Short-term Growth Catalysts"
            icon={<ArrowUpOutlined style={{ color: "#52c41a" }} />}
            content={report.short_term_growth_desc}
          />
        </Col>
        <Col span={12}>
          <SectionCard
            title="Long-term Growth Catalysts"
            icon={<ArrowUpOutlined style={{ color: "#52c41a" }} />}
            content={report.long_term_growth_desc}
          />
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

      {/* ── References ── */}
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
