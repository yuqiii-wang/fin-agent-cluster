import { Card, Space, Tag, Typography, theme } from "antd";
import type { TaskInfo } from "../../types";
import { sentimentColor } from "./helpers";

const { Text, Paragraph } = Typography;

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

export function NewsReferenceItem({ task }: { task: TaskInfo }) {
  const { token } = theme.useToken();
  const output = task.output as Record<string, unknown>;

  const rawList: unknown =
    output?.articles ?? output?.news ?? output?.items ?? output?.results ?? null;
  const articles: NewsArticle[] = Array.isArray(rawList)
    ? (rawList as NewsArticle[])
    : output
      ? [output as NewsArticle]
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
              {a.sector && <Tag color="blue" style={{ fontSize: 11 }}>{a.sector}</Tag>}
              {a.topic_level1 && <Tag style={{ fontSize: 11 }}>{a.topic_level1}</Tag>}
              {a.published_at && (
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {new Date(a.published_at).toLocaleString()}
                </Text>
              )}
            </Space>
            {a.title && (
              <Text strong style={{ fontSize: 13 }}>
                {a.url ? (
                  <a href={a.url} target="_blank" rel="noopener noreferrer">{a.title}</a>
                ) : (
                  a.title
                )}
              </Text>
            )}
            {a.ai_summary && (
              <Paragraph style={{ fontSize: 12, marginBottom: 0, color: token.colorTextSecondary }}>
                {a.ai_summary}
              </Paragraph>
            )}
          </Space>
        </Card>
      ))}
    </Space>
  );
}
