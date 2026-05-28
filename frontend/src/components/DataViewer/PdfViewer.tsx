/**
 * PdfViewer — renders a PDF document inside the DataViewer.
 *
 * Supported data shapes:
 *   { url: string }           — embeds the PDF by URL (external or API endpoint)
 *   { base64: string, filename?: string } — decodes base64 and creates a blob URL
 */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Space, Typography } from 'antd';
import { DownloadOutlined, FilePdfOutlined } from '@ant-design/icons';
import {
  COLOR_BORDER_BASE,
  COLOR_SURFACE_BASE,
  COLOR_TEXT_SECONDARY,
} from '../../constants/styleColors';

const { Text } = Typography;

export interface PdfData {
  url?: string;
  base64?: string;
  filename?: string;
}

export interface PdfViewerProps {
  data?: PdfData | unknown;
  maxHeight?: number;
  style?: React.CSSProperties;
}

const PdfViewer: React.FC<PdfViewerProps> = ({ data, maxHeight = 600, style }) => {
  const d = (data ?? {}) as PdfData;
  const blobUrlRef = useRef<string | null>(null);

  /** Resolve the URL to embed — either the raw URL or a blob created from base64. */
  const embedUrl = useMemo<string | null>(() => {
    if (d.url) return d.url;
    if (d.base64) {
      try {
        const binary = atob(d.base64);
        const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
        const blob = new Blob([bytes], { type: 'application/pdf' });
        const url = URL.createObjectURL(blob);
        blobUrlRef.current = url;
        return url;
      } catch {
        return null;
      }
    }
    return null;
  }, [d.url, d.base64]);

  /** Revoke the blob URL when the component unmounts. */
  useEffect(() => {
    return () => {
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current);
        blobUrlRef.current = null;
      }
    };
  }, []);

  const [embedFailed, setEmbedFailed] = useState(false);
  const filename = d.filename ?? 'document.pdf';

  const handleDownload = () => {
    if (!embedUrl) return;
    const a = document.createElement('a');
    a.href = embedUrl;
    a.download = filename;
    a.click();
  };

  const containerStyle: React.CSSProperties = {
    background: COLOR_SURFACE_BASE,
    border: `1px solid ${COLOR_BORDER_BASE}`,
    borderRadius: 6,
    overflow: 'hidden',
    ...style,
  };

  const header = (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '8px 14px',
        borderBottom: `1px solid ${COLOR_BORDER_BASE}`,
      }}
    >
      <Space size={6}>
        <FilePdfOutlined style={{ color: '#ff4d4f', fontSize: 16 }} />
        <Text style={{ color: COLOR_TEXT_SECONDARY, fontSize: 13 }}>{filename}</Text>
      </Space>
      {embedUrl && (
        <Button
          type="text"
          size="small"
          icon={<DownloadOutlined />}
          onClick={handleDownload}
          style={{ color: COLOR_TEXT_SECONDARY }}
        >
          Download
        </Button>
      )}
    </div>
  );

  if (!embedUrl || embedFailed) {
    return (
      <div style={containerStyle}>
        {header}
        <div style={{ padding: '24px 14px', textAlign: 'center' }}>
          <Text type="secondary">
            {embedUrl ? 'Unable to render PDF in this browser.' : 'No PDF source available.'}
          </Text>
          {embedUrl && (
            <div style={{ marginTop: 12 }}>
              <Button icon={<DownloadOutlined />} onClick={handleDownload}>
                Download {filename}
              </Button>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div style={containerStyle}>
      {header}
      <iframe
        src={embedUrl}
        title={filename}
        width="100%"
        height={maxHeight}
        style={{ display: 'block', border: 'none' }}
        onError={() => setEmbedFailed(true)}
      />
    </div>
  );
};

export default PdfViewer;
