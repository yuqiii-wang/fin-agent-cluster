/**
 * refUtils — shared ref utilities for stable data-source-of-truth patterns.
 *
 * useLatestRef: always-current ref for callbacks and values — eliminates the
 * duplicated `const xRef = useRef(fn); xRef.current = fn;` pattern.
 */

export { useLatestRef } from './useLatestRef';
