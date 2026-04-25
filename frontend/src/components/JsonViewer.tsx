import { useState } from "react";
import { Button, Tooltip } from "antd";
import { CheckOutlined, CopyOutlined } from "@ant-design/icons";
import { useStyles } from "./JsonViewer.styles";

interface NodeProps {
  value: unknown;
  indent?: number;
  /** Auto-collapse objects/arrays when first rendered (used for nested nodes). */
  initCollapsed?: boolean;
}

/** Toggle arrow shown next to collapsible nodes. */
function ToggleArrow({ collapsed, onClick }: { collapsed: boolean; onClick: () => void }) {
  const styles = useStyles();
  return (
    <span onClick={onClick} style={styles.toggleArrow}>
      {collapsed ? "▶" : "▼"}
    </span>
  );
}

/** Recursively renders a parsed JSON value with syntax highlighting and collapsible nodes. */
function JsonNode({ value, indent = 0, initCollapsed = false }: NodeProps) {
  const { colors } = useStyles();
  const [collapsed, setCollapsed] = useState(initCollapsed);
  const toggle = () => setCollapsed((c) => !c);

  if (value === null) return <span style={{ color: colors.null }}>null</span>;
  if (typeof value === "boolean") return <span style={{ color: colors.boolean }}>{String(value)}</span>;
  if (typeof value === "number") return <span style={{ color: colors.number }}>{value}</span>;
  if (typeof value === "string") return <span style={{ color: colors.string }}>"{value}"</span>;

  if (Array.isArray(value)) {
    if (value.length === 0) return <span style={{ color: colors.bracket }}>[]</span>;
    if (collapsed) {
      return (
        <>
          <ToggleArrow collapsed onClick={toggle} />
          <span style={{ color: colors.bracket, cursor: "pointer" }} onClick={toggle}>
            {"["}<span style={{ color: colors.summary, fontSize: 10 }}>{value.length} items</span>{"]"}
          </span>
        </>
      );
    }
    return (
      <>
        <ToggleArrow collapsed={false} onClick={toggle} />
        <span style={{ color: colors.bracket }}>{"["}</span>
        {value.map((item, i) => (
          <div key={i} style={{ paddingLeft: 16 }}>
            <JsonNode value={item} indent={indent + 1} initCollapsed={indent >= 1} />
            {i < value.length - 1 && <span style={{ color: colors.bracket }}>,</span>}
          </div>
        ))}
        <div><span style={{ color: colors.bracket }}>{"]"}</span></div>
      </>
    );
  }

  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return <span style={{ color: colors.bracket }}>{"{}"}</span>;
    if (collapsed) {
      return (
        <>
          <ToggleArrow collapsed onClick={toggle} />
          <span style={{ color: colors.bracket, cursor: "pointer" }} onClick={toggle}>
            {"{"}<span style={{ color: colors.summary, fontSize: 10 }}>{entries.length} keys</span>{"}"}
          </span>
        </>
      );
    }
    return (
      <>
        <ToggleArrow collapsed={false} onClick={toggle} />
        <span style={{ color: colors.bracket }}>{"{"}</span>
        {entries.map(([k, v], i) => (
          <div key={k} style={{ paddingLeft: 16 }}>
            <span style={{ color: colors.key }}>"{k}"</span>
            <span style={{ color: colors.bracket }}>: </span>
            <JsonNode value={v} indent={indent + 1} initCollapsed={indent >= 1} />
            {i < entries.length - 1 && <span style={{ color: colors.bracket }}>,</span>}
          </div>
        ))}
        <div><span style={{ color: colors.bracket }}>{"}"}</span></div>
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
  const styles = useStyles();
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
    <div style={styles.container}>
      {isComplex && (
        <Tooltip title="Copy JSON">
          <Button
            size="small"
            type="text"
            icon={
              copied
                ? <CheckOutlined style={styles.copyIconSuccess} />
                : <CopyOutlined style={styles.copyIconDefault} />
            }
            style={styles.copyButton}
            onClick={handleCopy}
          />
        </Tooltip>
      )}
      <div
        style={{ ...styles.viewer, maxHeight }}
      >
        <JsonNode value={parsed} />
      </div>
    </div>
  );
}
