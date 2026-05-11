/**
 * MarkdownViewer — renders a markdown string inside a styled box.
 */

import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { COLOR_BORDER_BASE, COLOR_SURFACE_BASE } from '../../constants/styleColors';

interface Props {
  text?: string;
  maxHeight?: number;
  style?: React.CSSProperties;
}

const mdBoxBase: React.CSSProperties = {
  background: COLOR_SURFACE_BASE,
  borderRadius: 6,
  padding: '10px 14px',
  border: `1px solid ${COLOR_BORDER_BASE}`,
};

const MarkdownViewer: React.FC<Props> = ({ text, maxHeight = 320, style }) => (
  <div style={{ ...mdBoxBase, maxHeight, overflowY: 'auto', ...style }}>
    <ReactMarkdown remarkPlugins={[remarkGfm]}>{text ?? ''}</ReactMarkdown>
  </div>
);

export default MarkdownViewer;
