import { useState } from "react";
import { Button, Tooltip, theme } from "antd";
import { CheckOutlined, CopyOutlined } from "@ant-design/icons";

interface NodeProps {
  value: unknown;
  indent?: number;
  /** Auto-collapse objects/arrays when first rendered (used for nested nodes). */
  initCollapsed?: boolean;
}

/** Toggle arrow shown next to collapsible nodes. */
function ToggleArrow({ collapsed, onClick }: { collapsed: boolean; onClick: () => void }) {
  return (
    <span
      onClick={onClick}
      style={{
        cursor: "pointer",
        userSelect: "none",
        fontSize: 10,
        marginRight: 2,
        display: "inline-block",
        width: 10,
        color: "#888",
      }}
    >
      {collapsed ? "▶" : "▼"}
    </span>
  );
}

/** Recursively renders a parsed JSON value with syntax highlighting and collapsible nodes. */
function JsonNode({ value, indent = 0, initCollapsed = false }: NodeProps) {
  const { token } = theme.useToken();
  const [collapsed, setCollapsed] = useState(initCollapsed);
  const toggle = () => setCollapsed((c) => !c);

  const color = {
    key: token.colorPrimary,
    string: "#52c41a",
    number: "#fa8c16",
    boolean: "#722ed1",
    null: token.colorTextDisabled,
    bracket: token.colorText,
  };

  if (value === null) return <span style={{ color: color.null }}>null</span>;
  if (typeof value === "boolean") return <span style={{ color: color.boolean }}>{String(value)}</span>;
  if (typeof value === "number") return <span style={{ color: color.number }}>{value}</span>;
  if (typeof value === "string") return <span style={{ color: color.string }}>"{value}"</span>;

  if (Array.isArray(value)) {
    if (value.length === 0) return <span style={{ color: color.bracket }}>[]</span>;
    if (collapsed) {
      return (
        <>
          <ToggleArrow collapsed onClick={toggle} />
          <span style={{ color: color.bracket, cursor: "pointer" }} onClick={toggle}>
            {"["}<span style={{ color: "#888", fontSize: 10 }}>{value.length} items</span>{"]"}
          </span>
        </>
      );
    }
    return (
      <>
        <ToggleArrow collapsed={false} onClick={toggle} />
        <span style={{ color: color.bracket }}>{"["}</span>
        {value.map((item, i) => (
          <div key={i} style={{ paddingLeft: 16 }}>
            <JsonNode value={item} indent={indent + 1} initCollapsed={indent >= 1} />
            {i < value.length - 1 && <span style={{ color: color.bracket }}>,</span>}
          </div>
        ))}
        <div><span style={{ color: color.bracket }}>{"]"}</span></div>
      </>
    );
  }

  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return <span style={{ color: color.bracket }}>{"{}"}</span>;
    if (collapsed) {
      return (
        <>
          <ToggleArrow collapsed onClick={toggle} />
          <span style={{ color: color.bracket, cursor: "pointer" }} onClick={toggle}>
            {"{"}<span style={{ color: "#888", fontSize: 10 }}>{entries.length} keys</span>{"}"}
          </span>
        </>
      );
    }
    return (
      <>
        <ToggleArrow collapsed={false} onClick={toggle} />
        <span style={{ color: color.bracket }}>{"{"}</span>
        {entries.map(([k, v], i) => (
          <div key={k} style={{ paddingLeft: 16 }}>
            <span style={{ color: color.key }}>"{k}"</span>
            <span style={{ color: color.bracket }}>: </span>
            <JsonNode value={v} indent={indent + 1} initCollapsed={indent >= 1} />
            {i < entries.length - 1 && <span style={{ color: color.bracket }}>,</span>}
          </div>
        ))}
        <div><span style={{ color: color.bracket }}>{"}"}</span></div>
      </>
    );
  }

  return <span>{String(value)}</span>;
}

interface Props {
  data: unknown;
  maxHeight?: number;
}

/** Syntax-highlighted, collapsible JSON viewer with copy button. */
export function JsonViewer({ data, maxHeight = 320 }: Props) {
  const { token } = theme.useToken();
  const [copied, setCopied] = useState(false);

  // data is already a parsed JS object; JSON.parse is only needed if a raw string is passed
  const parsed: unknown =
    typeof data === "string"
      ? (() => { try { return JSON.parse(data); } catch { return data; } })()
      : data;

  const isComplex = parsed !== null && typeof parsed === "object";

  const handleCopy = () => {
    navigator.clipboard.writeText(JSON.stringify(parsed, null, 2)).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div style={{ position: "relative" }}>
      {isComplex && (
        <Tooltip title="Copy JSON">
          <Button
            size="small"
            type="text"
            icon={
              copied
                ? <CheckOutlined style={{ color: token.colorSuccess, fontSize: 10 }} />
                : <CopyOutlined style={{ fontSize: 10 }} />
            }
            style={{
              position: "absolute",
              top: 4,
              right: 4,
              zIndex: 1,
              padding: "0 4px",
              height: 18,
            }}
            onClick={handleCopy}
          />
        </Tooltip>
      )}
      <div
        style={{
          fontFamily: "'Courier New', monospace",
          fontSize: 11,
          background: token.colorBgLayout,
          border: `1px solid ${token.colorBorder}`,
          borderRadius: token.borderRadius,
          padding: "6px 10px",
          marginTop: 2,
          maxHeight,
          overflowY: "auto",
          lineHeight: 1.6,
        }}
      >
        <JsonNode value={parsed} />
      </div>
    </div>
  );
}
