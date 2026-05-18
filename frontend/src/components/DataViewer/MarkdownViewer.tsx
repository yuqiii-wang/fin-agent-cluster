/**
 * MarkdownViewer — renders a markdown string inside a styled box.
 *
 * Supports:
 *  - GitHub Flavoured Markdown (tables, strikethrough, task lists, etc.)
 *  - Fenced code blocks with styled dark background and monospace font
 *  - Inline code styling
 */

import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Components } from 'react-markdown';
import {
  COLOR_BORDER_BASE,
  COLOR_BORDER_SUBTLE,
  COLOR_SURFACE_BASE,
  COLOR_TEXT_MUTED,
} from '../../constants/styleColors';

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

const mdComponents: Components = {
  code({ children, className, ...rest }) {
    const isBlock = !rest.node?.position || className?.startsWith('language-');
    if (isBlock) {
      return (
        <pre
          style={{
            background: '#1a1d23',
            border: `1px solid ${COLOR_BORDER_SUBTLE}`,
            borderRadius: 4,
            padding: '10px 12px',
            overflowX: 'auto',
            fontSize: 12,
            lineHeight: 1.6,
            margin: '8px 0',
          }}
        >
          <code
            className={className}
            style={{ fontFamily: "'Fira Code', 'Cascadia Code', Consolas, monospace", color: '#e6e6e6' }}
          >
            {children}
          </code>
        </pre>
      );
    }
    return (
      <code
        style={{
          background: '#1a1d23',
          border: `1px solid ${COLOR_BORDER_SUBTLE}`,
          borderRadius: 3,
          padding: '1px 5px',
          fontSize: '0.875em',
          fontFamily: "'Fira Code', 'Cascadia Code', Consolas, monospace",
          color: COLOR_TEXT_MUTED,
        }}
      >
        {children}
      </code>
    );
  },
  table({ children }) {
    return (
      <div style={{ overflowX: 'auto', margin: '8px 0' }}>
        <table
          style={{
            borderCollapse: 'collapse',
            width: '100%',
            fontSize: 12,
          }}
        >
          {children}
        </table>
      </div>
    );
  },
  th({ children }) {
    return (
      <th
        style={{
          border: `1px solid ${COLOR_BORDER_BASE}`,
          padding: '4px 10px',
          textAlign: 'left',
          background: '#1a1d23',
          fontWeight: 600,
        }}
      >
        {children}
      </th>
    );
  },
  td({ children }) {
    return (
      <td
        style={{
          border: `1px solid ${COLOR_BORDER_BASE}`,
          padding: '4px 10px',
        }}
      >
        {children}
      </td>
    );
  },
  blockquote({ children }) {
    return (
      <blockquote
        style={{
          borderLeft: `3px solid ${COLOR_BORDER_BASE}`,
          margin: '8px 0',
          padding: '4px 12px',
          color: COLOR_TEXT_MUTED,
          fontStyle: 'italic',
        }}
      >
        {children}
      </blockquote>
    );
  },
};

const MarkdownViewer: React.FC<Props> = ({ text, maxHeight = 320, style }) => (
  <div style={{ ...mdBoxBase, maxHeight, overflowY: 'auto', ...style }}>
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
      {text ?? ''}
    </ReactMarkdown>
  </div>
);

export default MarkdownViewer;
