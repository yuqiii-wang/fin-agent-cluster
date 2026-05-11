/**
 * StreamViewer — displays a live-streaming or completed LLM response.
 *
 * For streaming tasks the text is assembled token-by-token via the
 * useTokenStream hook; for completion tasks the output field is shown directly.
 */

import React, { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useTokenStream } from '../hooks/useTokenStream';
import type { TaskInfo } from '../types';

interface Props {
  task: TaskInfo;
  threadId: string;
  /** Live token text forwarded from the thread-level centrifugo-llm subscription. */
  liveStream?: string;
}

const STREAMING_TASK_NAMES = new Set(['stream_conclusion']);

const StreamViewer: React.FC<Props> = ({ task, threadId, liveStream }) => {
  const isStreaming = STREAMING_TASK_NAMES.has(task.task_name);
  const isRunning = task.status === 'running';

  const [tokens, setTokens] = useState<string[]>([]);
  const [streamDone, setStreamDone] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Use the per-task subscription only when no thread-level stream is provided.
  const shouldStream = isStreaming && isRunning && liveStream === undefined;

  useTokenStream({
    threadId,
    taskId: shouldStream ? task.task_id : null,
    active: shouldStream,
    onToken: (token) => setTokens((prev) => [...prev, token]),
    onEnd: () => setStreamDone(true),
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [tokens.length]);

  if (isStreaming) {
    // Prefer thread-level live stream if available; fall back to per-task
    // subscription tokens; then fall back to persisted output when done.
    const text =
      liveStream !== undefined
        ? liveStream
        : tokens.length > 0
        ? tokens.join('')
        : (task.output?.answer as string | undefined) ?? '';

    return (
      <div
        style={{
          maxHeight: 320,
          overflowY: 'auto',
          background: '#141414',
          borderRadius: 6,
          padding: '10px 14px',
          border: '1px solid #303030',
        }}
      >
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
        {isRunning && !streamDone && (
          <span style={{ display: 'inline-block', width: 8, height: 14, background: '#1677ff', marginLeft: 2, animation: 'blink 1s step-end infinite' }} />
        )}
        <div ref={bottomRef} />
      </div>
    );
  }

  // Completion task — show JSON output
  const output = task.output;
  const outputStr = output ? JSON.stringify(output, null, 2) : '(no output yet)';

  return (
    <pre
      style={{
        maxHeight: 280,
        overflowY: 'auto',
        background: '#141414',
        borderRadius: 6,
        padding: '10px 14px',
        border: '1px solid #303030',
        fontSize: 12,
        margin: 0,
        color: '#d9d9d9',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
      }}
    >
      {outputStr}
    </pre>
  );
};

export default StreamViewer;
