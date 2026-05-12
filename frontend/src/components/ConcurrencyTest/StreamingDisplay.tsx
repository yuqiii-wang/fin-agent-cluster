/**
 * StreamingDisplay — shows accumulated LLM token text for a concurrency test row.
 *
 * Polls a shared ref at 300ms.  When accumulated text exceeds the estimated
 * bounding-box capacity, only the tail is shown and the beginning is replaced
 * with a clickable "…" that expands to the full scrollable view.
 */

import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Button, Typography } from 'antd';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  COLOR_BORDER_SUBTLE,
  COLOR_BRAND_BLUE,
  COLOR_SURFACE_BASE,
  COLOR_TEXT_MUTED,
  COLOR_TEXT_SECONDARY,
} from '../../constants/styleColors';

const { Text } = Typography;

/** Approximate character capacity for a box of given pixel dimensions at font-size 12px. */
function estimateCapacity(widthPx: number): number {
  const CHAR_WIDTH = 6.5;   // px per character at font-size 12
  const LINE_HEIGHT = 18;   // px per line
  const BOX_HEIGHT = 200;   // px — collapsed bounding box height
  const charsPerLine = Math.max(1, Math.floor(widthPx / CHAR_WIDTH));
  const maxLines = Math.floor(BOX_HEIGHT / LINE_HEIGHT);
  return Math.floor(charsPerLine * maxLines * 0.75); // 75% safety factor
}

interface Props {
  /** Ref holding the accumulated token text written by useConcurrencyThread. */
  textRef: React.MutableRefObject<string>;
  /** True while the stream is still active. */
  isLive: boolean;
}

const StreamingDisplay: React.FC<Props> = ({ textRef, isLive }) => {
  const [displayText, setDisplayText] = useState('');
  const [expanded, setExpanded] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const scrollBoxRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(280);

  // Track container width via ResizeObserver.
  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerWidth(entry.contentRect.width);
      }
    });
    ro.observe(el);
    setContainerWidth(el.clientWidth || 280);
    return () => ro.disconnect();
  }, []);

  // Poll the ref at 300ms and flush to state for rendering.
  useEffect(() => {
    const tid = setInterval(() => {
      setDisplayText(textRef.current);
    }, 300);
    return () => clearInterval(tid);
  }, [textRef]);

  // Auto-scroll the inner box to bottom in tail mode without moving the page.
  useEffect(() => {
    if (!expanded && scrollBoxRef.current) {
      const el = scrollBoxRef.current;
      el.scrollTop = el.scrollHeight;
    }
  }, [displayText, expanded]);

  const capacity = estimateCapacity(containerWidth);
  const isTruncated = !expanded && displayText.length > capacity;
  const visibleText = isTruncated ? displayText.slice(-capacity) : displayText;

  return (
    <div ref={containerRef} style={{ marginTop: 6 }} onClick={(e) => e.stopPropagation()}>
      {isLive && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
          <Text style={{ fontSize: 11, color: COLOR_TEXT_SECONDARY, fontStyle: 'italic' }}>
            Thinking…
          </Text>
          <span
            style={{
              display: 'inline-block',
              width: 7,
              height: 7,
              borderRadius: '50%',
              background: COLOR_BRAND_BLUE,
              animation: 'blink 1s step-end infinite',
            }}
          />
        </div>
      )}
      <div
        ref={scrollBoxRef}
        style={{
          background: COLOR_SURFACE_BASE,
          borderRadius: 6,
          border: `1px solid ${COLOR_BORDER_SUBTLE}`,
          padding: '8px 12px',
          maxHeight: expanded ? 400 : 200,
          overflowY: 'auto',
          color: COLOR_TEXT_MUTED,
          fontSize: 12,
          fontStyle: 'italic',
        }}
      >
        {/* Clickable "…" to expand truncated beginning */}
        {isTruncated && (
          <span
            onClick={(e) => { e.stopPropagation(); setExpanded(true); }}
            title="Show full streaming text"
            style={{
              cursor: 'pointer',
              color: COLOR_BRAND_BLUE,
              fontWeight: 700,
              fontStyle: 'normal',
              fontSize: 13,
              display: 'block',
              marginBottom: 4,
              userSelect: 'none',
            }}
          >
            …
          </span>
        )}
        {/* Collapse button when expanded */}
        {expanded && displayText.length > 0 && (
          <Button
            size="small"
            type="text"
            onClick={(e) => { e.stopPropagation(); setExpanded(false); }}
            style={{ fontSize: 11, padding: '0 4px', marginBottom: 4, display: 'block' }}
          >
            ↑ collapse
          </Button>
        )}
        {displayText ? (
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{visibleText}</ReactMarkdown>
        ) : (
          <Text type="secondary" style={{ fontSize: 11 }}>
            No tokens yet.
          </Text>
        )}
      </div>
    </div>
  );
};

export default StreamingDisplay;
