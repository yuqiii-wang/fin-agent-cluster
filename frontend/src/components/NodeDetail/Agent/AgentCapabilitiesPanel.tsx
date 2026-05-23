/**
 * AgentCapabilitiesPanel — displays the fixed tools registered on an agent node.
 *
 * Tools are static for the lifetime of the agent (determined at class definition).
 * Each tool row shows its name and description.  The input schema is shown on click.
 */

import React, { useState } from 'react';
import { Collapse, Tag, Typography } from 'antd';
import { ApiOutlined } from '@ant-design/icons';
import { COLOR_TEXT_SECONDARY } from '../../../constants/styleColors';
import type { ToolInfo } from '../../../types';

const { Text } = Typography;

interface Props {
  tools: ToolInfo[];
}

const AgentCapabilitiesPanel: React.FC<Props> = ({ tools }) => {
  if (tools.length === 0) {
    return <Text type="secondary" style={{ fontSize: 12 }}>No tools registered.</Text>;
  }

  return (
    <>
      <Text strong style={{ fontSize: 12, color: COLOR_TEXT_SECONDARY, display: 'block', marginBottom: 6 }}>
        TOOLS ({tools.length})
      </Text>
      <Collapse
        size="small"
        ghost
        items={tools.map((tool) => ({
          key: tool.name,
          label: (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <ApiOutlined style={{ fontSize: 12, color: COLOR_TEXT_SECONDARY }} />
              <Text style={{ fontSize: 12 }}>{tool.name}</Text>
              <Tag style={{ fontSize: 10, marginLeft: 'auto' }}>tool</Tag>
            </div>
          ),
          children: (
            <div style={{ paddingLeft: 4 }}>
              {tool.description && (
                <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 4 }}>
                  {tool.description}
                </Text>
              )}
              {Object.keys(tool.input_schema).length > 0 && (
                <pre style={{ fontSize: 10, margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                  {JSON.stringify(tool.input_schema, null, 2)}
                </pre>
              )}
              {!tool.description && Object.keys(tool.input_schema).length === 0 && (
                <Text type="secondary" style={{ fontSize: 11 }}>No schema available.</Text>
              )}
            </div>
          ),
        }))}
      />
    </>
  );
};

export default AgentCapabilitiesPanel;
