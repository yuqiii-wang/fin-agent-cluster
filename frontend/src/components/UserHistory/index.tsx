/**
 * UserHistory — sidebar panel with a "New Query" button, UUID search bar, and thread history list.
 */

import React, { useState } from 'react';
import { Button, Input, Spin, Typography } from 'antd';
import { PlusOutlined, SearchOutlined } from '@ant-design/icons';
import HistoryList from './HistoryList';
import type { ThreadSummary } from '../../types';
import { searchByUuid } from '../../api/threads';

const { Text } = Typography;

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

interface Props {
  history: ThreadSummary[];
  activeId: string | null;
  isAuthenticated: boolean;
  onSelect: (threadId: string) => void;
  onNewQuery: () => void;
}

const UserHistory: React.FC<Props> = ({ history, activeId, isAuthenticated, onSelect, onNewQuery }) => {
  const [searchText, setSearchText] = useState('');
  const [searchResult, setSearchResult] = useState<ThreadSummary | null | undefined>(undefined);
  const [searching, setSearching] = useState(false);

  const handleSearch = async (value: string) => {
    const trimmed = value.trim();
    if (!trimmed) {
      setSearchResult(undefined);
      return;
    }
    if (UUID_RE.test(trimmed)) {
      setSearching(true);
      setSearchResult(undefined);
      try {
        const result = await searchByUuid(trimmed);
        setSearchResult(result);
      } catch {
        setSearchResult(null);
      } finally {
        setSearching(false);
      }
    } else {
      setSearchResult(undefined);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setSearchText(val);
    if (!val.trim()) {
      setSearchResult(undefined);
    }
  };

  const isUuidSearch = UUID_RE.test(searchText.trim());
  const textFilter = !isUuidSearch ? searchText.trim().toLowerCase() : '';

  const displayedHistory: ThreadSummary[] = (() => {
    if (isUuidSearch) {
      if (searchResult === undefined) return [];
      if (searchResult === null) return [];
      return [searchResult];
    }
    if (textFilter) {
      return history.filter(
        (t) =>
          t.thread_id.toLowerCase().includes(textFilter) ||
          t.query.toLowerCase().includes(textFilter),
      );
    }
    return history;
  })();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '12px 8px' }}>
      <Button
        type="dashed"
        icon={<PlusOutlined />}
        block
        onClick={onNewQuery}
        style={{ marginBottom: 8, flexShrink: 0 }}
      >
        New Query
      </Button>

      <Input
        placeholder="Search query or UUID…"
        prefix={<SearchOutlined style={{ color: '#595959' }} />}
        value={searchText}
        onChange={handleChange}
        onPressEnter={() => handleSearch(searchText)}
        allowClear
        onClear={() => { setSearchText(''); setSearchResult(undefined); }}
        style={{ marginBottom: 8, flexShrink: 0 }}
        size="small"
      />

      {!isAuthenticated && (
        <Text type="secondary" style={{ fontSize: 11, display: 'block', textAlign: 'center', marginBottom: 8, flexShrink: 0 }}>
          Login to persist history
        </Text>
      )}

      {searching && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '8px 0', flexShrink: 0 }}>
          <Spin size="small" />
        </div>
      )}

      {isUuidSearch && !searching && searchResult === null && (
        <Text type="secondary" style={{ fontSize: 11, display: 'block', textAlign: 'center', padding: '8px 0', flexShrink: 0 }}>
          No thread found for this UUID
        </Text>
      )}

      <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
        <HistoryList history={displayedHistory} activeId={activeId} onSelect={onSelect} />
      </div>
    </div>
  );
};

export default UserHistory;
