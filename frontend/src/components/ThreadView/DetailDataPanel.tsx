import React, { useEffect, useState } from 'react';
import { Button, Card, Typography } from 'antd';
import DataViewer from '../DataViewer/index';
import { StatsViewSelect } from '../DataViewer/StatsViewer';
import type { TaskInfo } from '../../types';
import type { DetailData } from './types';

const { Text } = Typography;

interface Props {
  detailData: DetailData;
  onClose: () => void;
  tasks: TaskInfo[];
  threadId: string;
}

const DetailDataPanel: React.FC<Props> = ({ detailData, onClose, tasks, threadId }) => {
  const statsViews = (() => {
    const d = detailData.data as Record<string, unknown> | undefined;
    if (Array.isArray(d?.stats_views)) return d!.stats_views as string[];
    if (detailData.mode === 'mirror') {
      const taskId = d?.task_id as string | undefined;
      const resolved = taskId ? tasks.find(t => t.task_id === taskId) : undefined;
      const td = resolved?.output as Record<string, unknown> | undefined;
      if (Array.isArray(td?.stats_views)) return td!.stats_views as string[];
    }
    return [] as string[];
  })();

  const [activeStatsView, setActiveStatsView] = useState<string>(statsViews[0] ?? '');
  useEffect(() => {
    setActiveStatsView(statsViews[0] ?? '');
  }, [detailData.label]); // eslint-disable-line react-hooks/exhaustive-deps

  const resolvedMode = detailData.mode ??
    (typeof detailData.data === 'string'
      ? 'markdown'
      : (detailData.data as Record<string, unknown> | null)?.df_split
      ? 'dataframe'
      : 'json');

  return (
    <Card
      size="small"
      title={<Text strong style={{ fontSize: 12 }}>{detailData.label}</Text>}
      extra={
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {statsViews.length > 0 && (
            <StatsViewSelect
              statsViews={statsViews}
              activeView={activeStatsView || statsViews[0]}
              onChange={setActiveStatsView}
            />
          )}
          <Button size="small" type="text" onClick={onClose}>✕</Button>
        </div>
      }
      style={{ borderRadius: 8 }}
    >
      <DataViewer
        mode={resolvedMode}
        data={typeof detailData.data !== 'string' ? detailData.data : undefined}
        text={typeof detailData.data === 'string' ? detailData.data : undefined}
        viewSchema={detailData.viewSchema}
        activeStatsView={activeStatsView || undefined}
        fieldList={detailData.fieldList}
        tasks={tasks}
        task={detailData.taskId ? tasks.find(t => t.task_id === detailData.taskId) : undefined}
        threadId={threadId}
        maxHeight={480}
      />
    </Card>
  );
};

export default DetailDataPanel;
