/**
 * JsonViewer — renders arbitrary data as formatted JSON.
 */

import React from 'react';
import {
  COLOR_BORDER_BASE, COLOR_SURFACE_BASE, COLOR_TEXT_BODY,
} from '../../constants/styleColors';

interface Props {
  data?: unknown;
  maxHeight?: number;
  style?: React.CSSProperties;
}

const preBase: React.CSSProperties = {
  background: COLOR_SURFACE_BASE,
  borderRadius: 6,
  padding: '10px 14px',
  border: `1px solid ${COLOR_BORDER_BASE}`,
  margin: 0,
  color: COLOR_TEXT_BODY,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
};

const JsonViewer: React.FC<Props> = ({ data, maxHeight = 320, style }) => {
  const str = data === undefined ? '(no data)' : JSON.stringify(data, null, 2);
  return (
    <pre
      style={{
        ...preBase,
        fontSize: 11,
        maxHeight,
        overflowY: 'auto',
        ...style,
      }}
    >
      {str}
    </pre>
  );
};

export default JsonViewer;
