/**
 * StatsDataFrame — renders a pandas split-orient DataFrame dict as an antd Table.
 *
 * Input shape (from ReadStatsOutput.df_split):
 *   { index: string[], columns: string[], data: number[][] }
 *
 * - Date column is injected from `index`.
 * - Volume column is formatted as integer; all other numeric columns to 4 dp.
 * - Every column is sortable.
 */

import React, { useMemo } from 'react';
import { Table } from 'antd';
import type { ColumnType } from 'antd/es/table';

export interface DfSplit {
  index: string[];
  columns: string[];
  data: number[][];
  index_label?: string;
}

interface Props {
  dfSplit: DfSplit;
  maxHeight?: number;
}

type RowRecord = Record<string, string | number>;

const DATE_KEY = 'date';

function fmtNumber(col: string, value: number): string {
  if (col === 'volume') return value.toLocaleString('en-US', { maximumFractionDigits: 0 });
  return value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
}

const StatsDataFrame: React.FC<Props> = ({ dfSplit, maxHeight = 320 }) => {
  const { index, columns, data } = dfSplit;
  const indexKey = dfSplit.index_label ?? DATE_KEY;
  const indexTitle = dfSplit.index_label ?? 'Date';

  const rows: RowRecord[] = useMemo(
    () =>
      index.map((label, i) => {
        const row: RowRecord = { [indexKey]: label };
        columns.forEach((col, j) => {
          row[col] = data[i]?.[j] ?? 0;
        });
        return row;
      }),
    [index, columns, data, indexKey],
  );

  const antColumns: ColumnType<RowRecord>[] = useMemo(() => {
    const idxCol: ColumnType<RowRecord> = {
      title: indexTitle,
      dataIndex: indexKey,
      key: indexKey,
      fixed: 'left',
      width: 100,
      sorter: (a, b) => String(a[indexKey]).localeCompare(String(b[indexKey])),
    };

    const dataCols: ColumnType<RowRecord>[] = columns.map((col) => ({
      title: col,
      dataIndex: col,
      key: col,
      align: 'right' as const,
      width: col === 'volume' ? 120 : 90,
      sorter: (a: RowRecord, b: RowRecord) => (a[col] as number) - (b[col] as number),
      render: (val: number) => fmtNumber(col, val),
    }));

    return [idxCol, ...dataCols];
  }, [columns, indexKey, indexTitle]);

  if (!index.length) {
    return <span style={{ fontSize: 12, opacity: 0.5 }}>No data</span>;
  }

  return (
    <Table<RowRecord>
      dataSource={rows}
      columns={antColumns}
      rowKey={indexKey}
      size="small"
      pagination={false}
      scroll={{ x: 'max-content', y: maxHeight }}
      style={{ fontSize: 12 }}
    />
  );
};

export default StatsDataFrame;
