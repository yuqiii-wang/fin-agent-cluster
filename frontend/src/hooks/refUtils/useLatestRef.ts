/**
 * useLatestRef — always holds the latest value of a prop or callback without
 * triggering re-renders or requiring it as an effect dependency.
 *
 * This is the canonical solution to the stale-closure problem for callbacks
 * passed into long-lived subscriptions (Centrifugo, timers, etc.):
 *
 *   // Before — pattern duplicated in every hook:
 *   const onTokenRef = useRef(onToken);
 *   onTokenRef.current = onToken;
 *
 *   // After:
 *   const onTokenRef = useLatestRef(onToken);
 *
 * The ref is synchronously updated during render (before any effects fire),
 * so handlers that access `ref.current` always call the latest version.
 * Safe to use for any non-primitive value: functions, objects, primitives.
 */

import { useRef, type MutableRefObject } from 'react';

export function useLatestRef<T>(value: T): MutableRefObject<T> {
  const ref = useRef<T>(value);
  ref.current = value;
  return ref;
}
