import { Card, Space, Typography, theme } from "antd";
import type { ReactNode } from "react";
import { MdSection } from "./MdSection";

const { Text } = Typography;

interface SectionCardProps {
  title: string;
  icon?: ReactNode;
  content: string | null | undefined;
  extra?: ReactNode;
}

export function SectionCard({ title, icon, content, extra }: SectionCardProps) {
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
        body: { padding: "12px 16px", background: token.colorBgContainer },
        header: { background: token.colorBgLayout },
      }}
      style={{ marginBottom: 12 }}
    >
      <MdSection content={content} />
    </Card>
  );
}
