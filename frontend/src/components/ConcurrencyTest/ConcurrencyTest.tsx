/**
 * ConcurrencyTest — test mode component.
 *
 * Test mode is not supported. This component is a placeholder.
 */

import React from 'react';
import { Alert } from 'antd';
import type { QueryResponse } from '../../types';

interface Props {
  initialResults: QueryResponse[];
  onSelectThread: (threadId: string) => void;
  onStatusUpdate: (threadId: string, status: string) => void;
}

const ConcurrencyTest: React.FC<Props> = () => (
  <Alert
    type="warning"
    message="Test mode not supported"
    description="The concurrency test grid has been disabled."
    showIcon
  />
);

export default ConcurrencyTest;
