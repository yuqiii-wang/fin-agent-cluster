import React, { useCallback, useRef, useState } from 'react';
import { Button, Card, Select, Splitter, Typography } from 'antd';
import { BranchesOutlined, MenuFoldOutlined, MenuUnfoldOutlined } from '@ant-design/icons';
import NodeGraph from '../NodeGraph';
import NodeDetail from '../NodeDetail/index';
import { COLOR_BORDER_PANEL } from '../../constants/styleColors';
import type { NodeInfo, GraphTopology, TaskInfo, TaskRunEntry } from '../../types';
import type { DataViewerMode } from '../DataViewer/index';

const { Text } = Typography;

interface Props {
  versionNodes: NodeInfo[];
  topology: GraphTopology | null;
  selectedNodeId: string | null;
  onSelectNode: (id: string | null) => void;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  activeVersion: number;
  maxVersion: number;
  versionOptions: { value: number; label: string }[];
  onVersionChange: (v: number) => void;
  selectedNode: NodeInfo | null;
  tasks: TaskInfo[];
  threadId: string;
  tokenStreams: Record<string, string>;
  taskRunLog: TaskRunEntry[];
  threadActive: boolean;
  cancelling: string | null;
  onViewData: (
    label: string,
    data: unknown,
    opts?: { mode?: DataViewerMode; viewSchema?: Record<string, string>; fieldList?: boolean; nodeContext?: 'input' | 'output' },
  ) => void;
  onCancelNode: (nodeId: string) => void;
  onCancelTask: (taskId: string, nodeId?: string) => void;
  onReExplore: (node: NodeInfo) => void;
}

const NodeGraphPanel: React.FC<Props> = ({
  versionNodes, topology, selectedNodeId, onSelectNode,
  sidebarOpen, onToggleSidebar,
  activeVersion, maxVersion, versionOptions, onVersionChange,
  selectedNode, tasks, threadId, tokenStreams, taskRunLog, threadActive, cancelling,
  onViewData, onCancelNode, onCancelTask, onReExplore,
}) => {
  const handleSelect = (id: string) => onSelectNode(id === selectedNodeId ? null : id);

  const [graphHeight, setGraphHeight] = useState(380);
  const dragStartY = useRef<number | null>(null);
  const dragStartH = useRef(380);

  const handleDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragStartY.current = e.clientY;
    dragStartH.current = graphHeight;
    const onMove = (me: MouseEvent) => {
      if (dragStartY.current === null) return;
      const delta = me.clientY - dragStartY.current;
      setGraphHeight(Math.max(150, Math.min(900, dragStartH.current + delta)));
    };
    const onUp = () => {
      dragStartY.current = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [graphHeight]);

  return (
    <Card
      size="small"
      title={
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Text strong>Node Graph</Text>
          {maxVersion > 0 && (
            <Select
              size="small"
              value={activeVersion}
              options={versionOptions}
              onChange={onVersionChange}
              style={{ width: 140 }}
              suffixIcon={<BranchesOutlined />}
            />
          )}
        </div>
      }
      extra={
        <Button
          size="small" type="text"
          icon={sidebarOpen ? <MenuFoldOutlined /> : <MenuUnfoldOutlined />}
          onClick={onToggleSidebar}
          title={sidebarOpen ? 'Hide details' : 'Show details'}
        />
      }
      style={{ borderRadius: 8 }}
      styles={{ body: { padding: 0 } }}
    >
      {sidebarOpen && selectedNode ? (
        <Splitter style={{ height: graphHeight }}>
          <Splitter.Panel defaultSize="60%" min="40%">
            <div style={{ padding: '8px 0', overflowY: 'auto', height: '100%', boxSizing: 'border-box' }}>
              <NodeGraph
                nodes={versionNodes}
                topology={topology}
                selectedNodeId={selectedNodeId}
                onSelectNode={handleSelect}
              />
            </div>
          </Splitter.Panel>
          <Splitter.Panel>
            <div style={{ padding: 16, overflowY: 'auto', height: '100%', borderLeft: `1px solid ${COLOR_BORDER_PANEL}` }}>
              <NodeDetail
                node={selectedNode}
                nodes={versionNodes}
                tasks={tasks}
                threadId={threadId}
                tokenStreams={tokenStreams}
                taskRunLog={taskRunLog}
                threadActive={threadActive}
                activeVersion={activeVersion}
                onViewData={onViewData}
                onSelectNode={handleSelect}
                onCancelNode={onCancelNode}
                onCancelTask={onCancelTask}
                cancellingId={cancelling}
                onReExplore={onReExplore}
              />
            </div>
          </Splitter.Panel>
        </Splitter>
      ) : (
        <div style={{ height: graphHeight, overflowY: 'auto' }}>
          <NodeGraph
            nodes={versionNodes}
            topology={topology}
            selectedNodeId={selectedNodeId}
            onSelectNode={handleSelect}
          />
        </div>
      )}
      {/* Drag handle — drag to resize the graph panel vertically */}
      <div
        onMouseDown={handleDragStart}
        style={{
          height: 6,
          cursor: 'ns-resize',
          background: 'transparent',
          borderTop: '2px solid rgba(255,255,255,0.08)',
          userSelect: 'none',
        }}
        title="Drag to resize"
      />
    </Card>
  );
};

export default NodeGraphPanel;
