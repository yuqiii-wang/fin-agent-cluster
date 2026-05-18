/**
 * WebRequestViewer — displays the result of a WebRequest task.
 *
 * Shows the URL (as a clickable link), page title, and a collapsible
 * content extract fetched from the web.
 */

import React from 'react';
import { Collapse, Space, Typography } from 'antd';
import { LinkOutlined } from '@ant-design/icons';
import {
  COLOR_BORDER_BASE,
  COLOR_BORDER_SUBTLE,
  COLOR_SURFACE_BASE,
  COLOR_TEXT_MUTED,
  COLOR_TEXT_SECONDARY,
} from '../../constants/styleColors';

const { Text, Link } = Typography;

export interface WebRequestData {
  url?: string;
  title?: string;
  content?: string;
}

export interface WebRequestViewerProps {
  data?: WebRequestData | unknown;
  maxHeight?: number;
  style?: React.CSSProperties;
}

const WebRequestViewer: React.FC<WebRequestViewerProps> = ({ data, maxHeight = 320, style }) => {
  const d = (data ?? {}) as WebRequestData;
  const hasContent = !!d.content;

  const containerStyle: React.CSSProperties = {
    background: COLOR_SURFACE_BASE,
    border: `1px solid ${COLOR_BORDER_BASE}`,
    borderRadius: 6,
    padding: '10px 14px',
    ...style,
  };

  const metaSection = (
    <Space direction="vertical" size={2} style={{ width: '100%' }}>
      {d.title && (
        <Text strong style={{ fontSize: 13 }}>
          {d.title}
        </Text>
      )}
      {d.url ? (
        <Link
          href={d.url}
          target="_blank"
          rel="noopener noreferrer"
          style={{ fontSize: 12, wordBreak: 'break-all' }}
        >
          <LinkOutlined style={{ marginRight: 4 }} />
          {d.url}
        </Link>
      ) : (
        <Text type="secondary" style={{ fontSize: 12 }}>
          No URL retrieved
        </Text>
      )}
    </Space>
  );

  if (!hasContent) {
    return <div style={containerStyle}>{metaSection}</div>;
  }

  const contentPanels: import('antd').CollapseProps['items'] = [
    {
      key: 'content',
      label: (
        <Text style={{ fontSize: 12, color: COLOR_TEXT_SECONDARY }}>
          Page content
        </Text>
      ),
      children: (
        <pre
          style={{
            margin: 0,
            fontSize: 12,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            color: COLOR_TEXT_MUTED,
            maxHeight,
            overflowY: 'auto',
          }}
        >
          {d.content}
        </pre>
      ),
    },
  ];

  return (
    <div style={containerStyle}>
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        {metaSection}
        <Collapse
          size="small"
          ghost
          items={contentPanels}
          style={{ border: `1px solid ${COLOR_BORDER_SUBTLE}`, borderRadius: 4 }}
        />
      </Space>
    </div>
  );
};

export default WebRequestViewer;
