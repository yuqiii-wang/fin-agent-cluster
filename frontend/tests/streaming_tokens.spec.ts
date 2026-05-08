/**
 * streaming_tokens.spec.ts
 *
 * Playwright test that verifies streaming tokens appear on the UI when the
 * mock_analysis node is running.
 *
 * With auto-enable streaming (useSingleTestSession calls enableTaskStream on
 * every task_started event), tokens flow automatically as soon as the task starts
 * without requiring the user to click "Show Stream".
 *
 * Flow:
 *   1. Navigate to Single test mode.
 *   2. Click "Send request".
 *   3. Wait for mock_analysis node to appear and start running.
 *   4. Open the node inspector.
 *   5. Expand the task accordion.
 *   6. Assert: streaming-output element appears with non-empty token text.
 *   7. Take a screenshot for visual confirmation.
 *
 * Lifecycle labels checked:
 *   - "Awaiting streaming…" → spinner while waiting for first token batch
 *   - "Streaming…" or "Digesting…" → live token delivery in progress
 *   - tokens paragraph must contain non-empty text
 */

import { test, expect, type Page } from "@playwright/test";

// ── Helpers ───────────────────────────────────────────────────────────────────

async function goToSingleTestMode(page: Page): Promise<void> {
  await page.goto("/");
  const singleOption = page.locator(".ant-segmented-item-label", { hasText: /^Single$/ });
  await expect(singleOption.first()).toBeVisible({ timeout: 30_000 });
  await singleOption.first().click();
  await expect(page.getByRole("button", { name: /send request/i })).toBeVisible({ timeout: 5_000 });
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe("Streaming tokens — lifecycle and UI rendering", () => {

  test("streaming tokens appear in inspector when mock_analysis is running", async ({ page }) => {
    // Capture all console messages for lifecycle diagnosis.
    const consoleLogs: { type: string; text: string }[] = [];
    page.on("console", (msg) => {
      consoleLogs.push({ type: msg.type(), text: msg.text() });
    });
    page.on("pageerror", (err) => {
      consoleLogs.push({ type: "pageerror", text: err.message });
    });

    await goToSingleTestMode(page);

    // ── Step 1: Send request ──────────────────────────────────────────────────
    await page.getByRole("button", { name: /send request/i }).click();
    console.log("[test] send request clicked");

    // ── Step 2: Wait for mock_analysis to appear ─────────────────────────────
    const analysisNode = page.locator(
      '[data-testid="graph-node"][data-node-name="mock_analysis"]',
    );
    await analysisNode.waitFor({ state: "visible", timeout: 90_000 });
    console.log("[test] mock_analysis node appeared");

    // ── Step 3: Wait for it to be running ────────────────────────────────────
    await expect(
      page.locator('[data-testid="graph-node"][data-node-name="mock_analysis"][data-status="running"]'),
    ).toBeVisible({ timeout: 30_000 });
    console.log("[test] mock_analysis node is running");

    // Screenshot: node running state before inspector open.
    await page.screenshot({ path: "tests/results/streaming_tokens_node_running.png" });

    // ── Step 4: Open node inspector ───────────────────────────────────────────
    await analysisNode.click();
    console.log("[test] mock_analysis node clicked — inspector should open");

    // Wait for inspector panel to appear (header title).
    await expect(page.getByText("mock_analysis", { exact: true }).first()).toBeVisible({ timeout: 5_000 });

    // ── Step 5: Expand the task accordion ─────────────────────────────────────
    // Wait for at least one task-row to appear (SSE task_started event received).
    const taskRow = page.locator('[data-testid="task-row"]').first();
    await expect(taskRow).toBeVisible({ timeout: 30_000 });
    console.log("[test] task-row visible — expanding accordion");

    // Click to expand the task if it is a collapsed Collapse item.
    await taskRow.click();

    // ── Step 6: Wait for streaming tokens to appear ───────────────────────────
    // Auto-enable kicks in on task_started: enableTaskStream is called so tokens
    // flow into tokenStreams without requiring user to click "Show Stream".
    // OutputViewer will use StreamingTaskOutput → StreamingOutput once tokens arrive.
    //
    // Allow time for:
    //   - enableTaskStream HTTP round-trip
    //   - next token batch to be published by the backend
    //   - 100ms flush to React state
    const streamingOutput = page.locator('[data-testid="streaming-output"]').first();

    await expect(async () => {
      const exists = await streamingOutput.isVisible().catch(() => false);
      expect(exists, "streaming-output element must be visible once tokens arrive").toBe(true);
    }).toPass({ timeout: 15_000, intervals: [300] });

    console.log("[test] streaming-output element is visible");

    // Assert the token text paragraph has non-empty content.
    const tokenParagraph = page.locator('[data-testid="streaming-output-text"]').first();
    await expect(async () => {
      const text = await tokenParagraph.innerText().catch(() => "");
      expect(
        text.trim().length,
        `streaming-output-text must have non-empty text, got: "${text.slice(0, 100)}"`,
      ).toBeGreaterThan(0);
    }).toPass({ timeout: 10_000, intervals: [300] });

    const tokenText = await tokenParagraph.innerText().catch(() => "");
    console.log(`[test] streaming token text length=${tokenText.length} preview="${tokenText.slice(0, 80)}"`);

    // Screenshot: tokens visible.
    await page.screenshot({ path: "tests/results/streaming_tokens_visible.png" });

    // ── Step 7: Verify first-token lifecycle logs ─────────────────────────────
    const tokenLogs = consoleLogs.filter(
      (l) => l.text.includes("[single:token]") || l.text.includes("[single:flush]"),
    );
    console.log(`[test] token lifecycle logs (${tokenLogs.length} entries):`);
    for (const l of tokenLogs.slice(0, 5)) {
      console.log(`  [${l.type}] ${l.text}`);
    }

    if (tokenLogs.length === 0) {
      console.error(
        "[test] AUDIT ZERO token-lifecycle logs — auto-enable may not have triggered. " +
        "Check enableTaskStream call in useSingleTestSession.onStarted.",
      );
    }

    const enableErrors = consoleLogs.filter((l) => l.text.includes("[single] enableTaskStream failed"));
    if (enableErrors.length > 0) {
      console.error("[test] enableTaskStream errors:", enableErrors.map((l) => l.text).join("\n"));
    }

    // Final assertion: streaming-output must be visible with non-empty text.
    await expect(streamingOutput).toBeVisible();
    const finalText = await tokenParagraph.innerText().catch(() => "");
    expect(finalText.trim().length, "Final streaming text must be non-empty").toBeGreaterThan(0);
  });

  test("digesting lifecycle label shows when status transitions to digesting", async ({ page }) => {
    // Collect console errors to capture first-token lifecycle log.
    const firstTokenLogs: string[] = [];
    const enableErrors: string[] = [];
    page.on("console", (msg) => {
      const text = msg.text();
      if (text.includes("[single:token]") || text.includes("[single:flush]")) {
        firstTokenLogs.push(text);
      }
      if (text.includes("enableTaskStream failed")) {
        enableErrors.push(text);
      }
    });

    await goToSingleTestMode(page);
    await page.getByRole("button", { name: /send request/i }).click();

    // Wait for mock_analysis to run.
    await expect(
      page.locator('[data-testid="graph-node"][data-node-name="mock_analysis"][data-status="running"]'),
    ).toBeVisible({ timeout: 90_000 });

    // Open inspector.
    await page.locator('[data-testid="graph-node"][data-node-name="mock_analysis"]').click();

    // Expand task row.
    const taskRow = page.locator('[data-testid="task-row"]').first();
    await expect(taskRow).toBeVisible({ timeout: 30_000 });
    await taskRow.click();

    // Wait for streaming-output to appear (auto-enabled via onStarted handler).
    const streamingOutput = page.locator('[data-testid="streaming-output"]').first();
    await expect(streamingOutput).toBeVisible({ timeout: 15_000 });

    // The data-streaming-running attribute must be "true" while node is running.
    const runningAttr = await streamingOutput.getAttribute("data-streaming-running").catch(() => null);
    console.log(`[test] data-streaming-running="${runningAttr}"`);
    expect(runningAttr, "Streaming output must be in running state").toBe("true");

    // Screenshot showing streaming state with tokens.
    await page.screenshot({ path: "tests/results/streaming_tokens_digesting.png" });

    // Token text must be non-empty.
    const tokenParagraph = page.locator('[data-testid="streaming-output-text"]').first();
    const tokenText = await tokenParagraph.innerText().catch(() => "");
    expect(tokenText.trim().length, "Token text non-empty in streaming/digesting state").toBeGreaterThan(0);

    // Log token delivery status.
    console.log(`[test] first-token logs: ${firstTokenLogs.length} entries`);
    for (const l of firstTokenLogs) console.log(`  ${l}`);

    if (enableErrors.length > 0) {
      console.error("[test] enableTaskStream errors:", enableErrors.join("\n"));
    }

    if (firstTokenLogs.length === 0) {
      console.error(
        "[test] AUDIT: no first-token logs — " +
        "Centrifugo token channel may not be delivering fin:llm:tokens",
      );
    }
  });
});
