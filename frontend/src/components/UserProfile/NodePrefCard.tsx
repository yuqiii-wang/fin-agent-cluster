/**
 * NodePrefCard — renders configurable fields for one graph node.
 */

import React from 'react';
import { Card, Form, InputNumber, Select, Switch, Tooltip, Typography } from 'antd';
import { InfoCircleOutlined } from '@ant-design/icons';
import type { NodeConfig } from '../../types';
import type { NodeMeta } from './nodeMeta';

const { Text } = Typography;

interface Props {
  meta: NodeMeta;
  values: NodeConfig;
  onChange: (nodeName: string, patch: NodeConfig) => void;
  saving: boolean;
}

const NodePrefCard: React.FC<Props> = ({ meta, values, onChange, saving }) => {
  function patch(key: keyof NodeConfig, value: NodeConfig[keyof NodeConfig]) {
    onChange(meta.node_name, { ...values, [key]: value });
  }

  return (
    <Card
      size="small"
      title={
        <Text strong style={{ fontSize: 13 }}>
          {meta.display_name}
        </Text>
      }
      style={{ marginBottom: 8 }}
    >
      <Form layout="vertical" size="small">
        {meta.fields.map((field) => (
          <Form.Item
            key={field.key}
            label={
              <span>
                {field.label}{' '}
                <Tooltip title={field.description}>
                  <InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 11 }} />
                </Tooltip>
              </span>
            }
            style={{ marginBottom: 8 }}
          >
            {field.type === 'boolean' && (
              <Switch
                size="small"
                checked={Boolean(values[field.key])}
                onChange={(checked) => patch(field.key, checked)}
                disabled={saving}
              />
            )}
            {field.type === 'select' && (
              <Select
                size="small"
                style={{ width: 220 }}
                value={(values[field.key] as string | undefined) ?? undefined}
                placeholder="System default"
                allowClear
                onChange={(val) => patch(field.key, val ?? undefined)}
                disabled={saving}
                options={field.options}
              />
            )}
            {field.type === 'number' && (
              <InputNumber
                size="small"
                min={field.min}
                max={field.max}
                step={field.step}
                value={values[field.key] as number | undefined}
                placeholder="Default"
                onChange={(val) => patch(field.key, val ?? undefined)}
                disabled={saving}
              />
            )}
          </Form.Item>
        ))}
      </Form>
    </Card>
  );
};

export default NodePrefCard;
