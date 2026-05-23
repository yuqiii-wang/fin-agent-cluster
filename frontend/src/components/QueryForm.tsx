/**
 * QueryForm — test mode query form.
 *
 * Test mode is not supported. Use MainQuery for production queries.
 */

import React from 'react';
import { Alert } from 'antd';
import type { QueryResponse } from '../types';

interface Props {
  onSubmit: (result: QueryResponse) => void;
  onConcurrencySubmit?: (results: QueryResponse[]) => void;
}

const QueryForm: React.FC<Props> = () => (
  <Alert
    type="warning"
    message="Test mode not supported"
    description="The test query form has been disabled. Use the main query interface."
    showIcon
  />
);

export default QueryForm;

