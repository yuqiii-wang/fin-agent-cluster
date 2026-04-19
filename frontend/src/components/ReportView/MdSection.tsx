import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { theme } from "antd";
import type { CSSProperties } from "react";
import { ABSENT_TAG } from "./helpers";



interface MdProps {
  content: string | null | undefined;
  monoBg?: string;
}

export function MdSection({ content, monoBg }: MdProps) {
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
            <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: 8, fontSize: 13 }}>
              {children}
            </table>
          ),
          th: ({ children }) => (
            <th style={{ border: `1px solid ${token.colorBorder}`, padding: "6px 10px", background: token.colorBgLayout, textAlign: "left" }}>
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td style={{ border: `1px solid ${token.colorBorder}`, padding: "5px 10px" }}>
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
