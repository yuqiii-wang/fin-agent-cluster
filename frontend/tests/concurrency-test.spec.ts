/**
 * Playwright test: concurrency test grid — 5 concurrent streaming threads.
 *
 * Assertions:
 *  - All thread rows reach "Completed" status (not stuck at "Running").
 *  - All rows with LLM streaming have tokens > 0.
 *  - All rows show 100% ACK confirmation.
 *
 * Run:
 *   cd frontend && npx playwright test tests/concurrency-test.spec.ts --headed
 *
 * Timing notes:
 *  - stream_start handshake + LLM MQ setup: ~8 s per thread
 *  - LLM stream duration: 10 s at 30 tok/s = 300 tokens
 *  - Total per-thread wall time: ~20-25 s; allow up to 3 min for 5 concurrent.
 */

import { expect, test } from '@playwright/test';

const CONCURRENCY = 5;
// Budget: ~8s MQ setup + 10s stream + generous buffer for 5 concurrent threads.
const COMPLETION_TIMEOUT_MS = 180_000;

// Column indices in antd table body rows (leaf columns, 0-based):
// 0: Thread ID | 1: Thread Status | 2: Stream Task | 3: Latency
// 4: MQ | 5: TPS | 6: Tokens | 7: Sent | 8: Confirmed | 9: ACK%
const COL = { STATUS: 1, TOKENS: 6, ACK_PCT: 9 } as const;

test('concurrency test grid — 5 threads all complete with tokens and 100% acks', async ({ page }) => {
  // ── Diagnostics ──────────────────────────────────────────────────────────
  page.on('console', (msg) => {
    if (msg.type() === 'error') console.log(`[browser error] ${msg.text()}`);
  });
  page.on('pageerror', (err) => console.error(`[page error] ${err.message}`));
  page.on('response', async (resp) => {
    const url = resp.url();
    if (url.includes('/threads/query')) {
      const status = resp.status();
      let body = '';
      try { body = await resp.text(); } catch (_) { /* ignore */ }
      console.log(`[network] POST /threads/query → ${status} ${body.slice(0, 120)}`);
    }
  });
  page.on('websocket', (ws) => {
    const label = ws.url().replace(/^wss:\/\/[^/]+/, '');
    console.log(`[ws open] ${label}`);
    ws.on('socketerror', (err) => console.log(`[ws error] ${label} ${err}`));
  });

  // ── Navigate ─────────────────────────────────────────────────────────────
  await page.goto('https://localhost:3000', { waitUntil: 'domcontentloaded' });
  await expect(page.getByText('Fin Agent Query')).toBeVisible({ timeout: 15_000 });

  // ── Select Concurrency Test mode ─────────────────────────────────────────
  const concurrencyRadio = page.getByRole('radio', { name: 'Concurrency Test' });
  await expect(concurrencyRadio).toBeVisible({ timeout: 10_000 });
  await concurrencyRadio.click();
  await expect(concurrencyRadio).toBeChecked();

  // ── Fill form fields via .ant-form-item label proximity ──────────────────
  const durationItem = page.locator('.ant-form-item').filter({ hasText: 'Duration (seconds)' });
  const tpsItem = page.locator('.ant-form-item').filter({ hasText: 'Tokens per second' });
  const concurrencyItem = page.locator('.ant-form-item').filter({ hasText: 'Concurrency (number of requests)' });

  await durationItem.locator('input').fill('10');
  await tpsItem.locator('input').fill('30');
  await concurrencyItem.locator('input').fill(String(CONCURRENCY));

  // ── Submit ────────────────────────────────────────────────────────────────
  const submitBtn = page.getByRole('button', { name: /submit/i });
  await submitBtn.click();
  console.log(`[test] Submitted ${CONCURRENCY} concurrent queries`);

  // ── Wait for concurrency grid to appear ──────────────────────────────────
  await expect(page.getByText(`Concurrency Test — ${CONCURRENCY} threads`)).toBeVisible({
    timeout: 30_000,
  });
  console.log('[test] Grid visible');
  await page.screenshot({ path: 'tests/results/concurrency-grid-start.png', fullPage: true });

  // ── Wait for all threads to complete ─────────────────────────────────────
  // Poll strategy: count Completed status tags in ACTUAL data rows only.
  // Use `tr.ant-table-row` to skip antd header rows that also render inside <tbody>
  // for grouped column tables. Do NOT use Running=0 because threads start as
  // "received" (not "Running"), which would give a false-positive immediately.
  console.log('[test] Polling for all threads Completed (MQ setup ~8 s + stream 10 s per thread)...');

  await expect.poll(
    async () => {
      // tr.ant-table-row are the actual data rows rendered by antd Table.
      const rows = page.locator('tr.ant-table-row');
      const rowCount = await rows.count();
      if (rowCount < CONCURRENCY) return `grid not ready: ${rowCount} rows`;

      let completed = 0;
      let running = 0;
      for (let i = 0; i < rowCount; i++) {
        const statusText = (await rows.nth(i).locator('td').nth(COL.STATUS).textContent())?.trim() ?? '';
        if (statusText === 'Completed') completed++;
        else if (statusText === 'Running') running++;
      }
      console.log(`[test poll] ${completed} Completed / ${running} Running / ${rowCount} total`);
      return completed;
    },
    { timeout: COMPLETION_TIMEOUT_MS, intervals: [3_000] },
  ).toBe(CONCURRENCY);

  console.log('[test] All threads Completed!');
  await page.screenshot({ path: 'tests/results/concurrency-grid-completed.png', fullPage: true });

  // ── Per-row assertions ────────────────────────────────────────────────────
  const rows = page.locator('tr.ant-table-row');
  const rowCount = await rows.count();
  console.log(`[test] Asserting ${rowCount} data rows`);

  let completedCount = 0;
  let tokensOkCount = 0;
  let ackPctOkCount = 0;

  for (let i = 0; i < rowCount; i++) {
    const cells = rows.nth(i).locator('td');

    // Thread Status
    const statusText = (await cells.nth(COL.STATUS).textContent())?.trim() ?? '';
    console.log(`[test] Row ${i + 1} status="${statusText}"`);
    if (statusText === 'Completed') completedCount++;

    // Tokens: rendered as "N / totalSeq" after stream ends, or just "N" while streaming.
    // After completion all rows should show "N / M" with N > 0.
    const tokensText = (await cells.nth(COL.TOKENS).textContent())?.trim() ?? '';
    const received = parseInt(tokensText.split(' / ')[0] ?? '0', 10);
    console.log(`[test] Row ${i + 1} tokens="${tokensText}" received=${received}`);
    if (received > 0) tokensOkCount++;

    // ACK%
    const ackPctText = (await cells.nth(COL.ACK_PCT).textContent())?.trim() ?? '';
    console.log(`[test] Row ${i + 1} ack%="${ackPctText}"`);
    if (ackPctText === '100%') ackPctOkCount++;
  }

  console.log(
    `[test] Summary: completed=${completedCount}/${CONCURRENCY}` +
    ` tokens_ok=${tokensOkCount}/${CONCURRENCY}` +
    ` ack_100pct=${ackPctOkCount}/${CONCURRENCY}`,
  );

  expect(completedCount, `Expected all ${CONCURRENCY} threads to be Completed`).toBe(CONCURRENCY);
  expect(tokensOkCount, `Expected all ${CONCURRENCY} threads to have tokens > 0`).toBe(CONCURRENCY);
  expect(ackPctOkCount, `Expected all ${CONCURRENCY} threads to have 100% ACK`).toBe(CONCURRENCY);

  await page.screenshot({ path: 'tests/results/concurrency-grid-final.png', fullPage: true });
  console.log('[test] PASS');
});

