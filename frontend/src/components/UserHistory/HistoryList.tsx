/**
 * HistoryList — scrollable list of thread history entries.
 */

import React from 'react';
import HistoryItem from './HistoryItem';
import type { ThreadSummary } from '../../types';

interface Props {
  history: ThreadSummary[];
  activeId: string | null;
  onSelect: (threadId: string) => void;
}

const HistoryList: React.FC<Props> = ({ history, activeId, onSelect }) => (
  <div>
    {history.map((entry) => (
      <HistoryItem
        key={entry.thread_id}
        entry={entry}
        isActive={entry.thread_id === activeId}
        onClick={() => onSelect(entry.thread_id)}
      />
    ))}
  </div>
);

export default HistoryList;
