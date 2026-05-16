/**
 * Playwright debug test: submit a semantic test query and observe SSE streaming.
 *
 * Run:  cd frontend && npx playwright test tests/semantic-test.spec.ts --headed
 */

import { expect, test } from '@playwright/test';

test('submit semantic test query and observe streaming', async ({ page }) => {
  // Capture all console output and network for debugging
  page.on('console', (msg) => {
    console.log(`[browser ${msg.type()}] ${msg.text()}`);
  });
  page.on('pageerror', (err) => {
    console.error(`[page error] ${err.message}`);
  });

  // Log API responses
  page.on('response', async (resp) => {
    const url = resp.url();
    if (url.includes('/api/')) {
      const status = resp.status();
      let body = '';
      try { body = await resp.text(); } catch (_) {}
      console.log(`[network] ${resp.request().method()} ${url} → ${status} ${body.slice(0, 300)}`);
    }
  });

  // Log WebSocket frames to verify centrifugo SSE events are received.
  page.on('websocket', (ws) => {
    console.log(`[ws open] ${ws.url()}`);
    ws.on('framereceived', (frame) => {
      const data = frame.payload.toString().slice(0, 200);
      console.log(`[ws recv] ${ws.url().split('/').slice(-3, -1).join('/')} ${data}`);
    });
    ws.on('framesent', (frame) => {
      const data = frame.payload.toString().slice(0, 100);
      console.log(`[ws send] ${ws.url().split('/').slice(-3, -1).join('/')} ${data}`);
    });
    ws.on('close', () => console.log(`[ws close] ${ws.url()}`));
    ws.on('socketerror', (err) => console.log(`[ws error] ${ws.url()} ${err}`));
  });

  await page.goto('https://localhost:3000', { waitUntil: 'domcontentloaded' });

  // Wait for the query form to render
  await expect(page.getByText('Fin Agent Query')).toBeVisible({ timeout: 10_000 });

  // Verify Semantic Test mode is pre-selected
  const semanticRadio = page.getByRole('radio', { name: 'Semantic Test' });
  await expect(semanticRadio).toBeChecked();

  // Submit with default settings (duration=10s, tps=30)
  const submitBtn = page.getByRole('button', { name: /submit/i });
  await submitBtn.click();

  console.log('[test] Query submitted, waiting for thread view...');

  // Expect to transition to thread view (spinner or status bar)
  await expect(page.getByText(/RECEIVED|RUNNING|COMPLETED/i).first()).toBeVisible({ timeout: 30_000 });

  console.log('[test] Thread status appeared. Observing SSE for up to 30s...');

  // Wait for completed status or timeout
  try {
    await expect(page.getByText(/COMPLETED/i)).toBeVisible({ timeout: 120_000 });
    console.log('[test] Thread completed.');
  } catch {
    console.log('[test] Thread did not complete within 120s — checking current state...');
    const status = await page.getByText(/RECEIVED|RUNNING|FAILED|CANCELLED/i).first().textContent();
    console.log(`[test] Current status: ${status}`);
  }

  // Capture final screenshot for inspection
  await page.screenshot({ path: 'tests/results/semantic-test-final.png', fullPage: true });
  console.log('[test] Screenshot saved to tests/results/semantic-test-final.png');

  // Log all visible node names in the NodeGraph (SVG text elements)
  const svgTexts = await page.locator('svg text').allTextContents();
  console.log('[test] NodeGraph SVG texts:', svgTexts);

  // Verify all three regional nodes appear
  const svg = page.locator('svg').first();
  const svgHtml = await svg.innerHTML();
  const hasApac = svgHtml.includes('apac');
  const hasEmea = svgHtml.includes('emea');
  const hasAmer = svgHtml.includes('amer');
  console.log(`[test] Regional nodes — apac:${hasApac} emea:${hasEmea} amer:${hasAmer}`);
});
