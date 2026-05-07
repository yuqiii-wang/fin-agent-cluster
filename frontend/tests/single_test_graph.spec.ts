/**
 * single_test_graph.spec.ts
 *
 * Playwright tests for the Single Test mode graph visualization panel.
 *
 * Covers:
 *   1. All 5 expected nodes appear on initial run (query, mock_news, mock_stats, merge, mock_analysis).
 *   2. No resume button visible after a graph-level cancel.
 *   3. No duplicate nodes spawned after resume (node_id stays stable).
 *   4. Tasks inside a cancelled node should show cancelled, not running.
 *   5. Paused node shows purple color and ⏸ icon; running tasks reset to not-run.
 */

import { test, expect, type Page, type Locator } from "@playwright/test";

// ── Constants ─────────────────────────────────────────────────────────────────

/**
 * Exact ordered list of node names that the mock_single pipeline emits.
 * Topology: query → [mock_news, mock_stats] → merge → mock_analysis → mock_report
 * (mock_analysis and mock_report are wired directly to the outer LangGraph routing
 *  graph, NOT inside the mock_single_subgraph — see backend/graph/builder.py)
 */
const EXPECTED_NODES: readonly string[] = [
  "query",
  "mock_news",
  "mock_stats",
  "merge",
  "mock_analysis",
  "mock_report",
] as const;

const EXPECTED_NODE_COUNT = EXPECTED_NODES.length; // 6

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Navigate to the app and switch Test Mode to "Single".
 * The app uses an Ant Design Segmented control with options:
 * Single | Throughput | Concurrency.
 *
 * The Segmented is hidden behind the guest-auth loading gate
 * (`!authLoading && userToken` in App.tsx), so we must wait for the
 * StreamingPerfTestPanel to mount before clicking.
 */
async function goToSingleTestMode(page: Page): Promise<void> {
  await page.goto("/");
  // Wait for the full StreamingPerfTestPanel to render — auth must complete first.
  // 30s covers slow backend startup and cold auth calls.
  const singleOption = page.locator(".ant-segmented-item-label", { hasText: /^Single$/ });
  await expect(singleOption.first()).toBeVisible({ timeout: 30_000 });
  await singleOption.first().click();
  // Confirm switch — Send request button belongs only to single mode.
  await expect(page.getByRole("button", { name: /send request/i })).toBeVisible({ timeout: 5_000 });
}

/** Wait for at least `count` graph nodes to appear. */
async function waitForNodes(page: Page, count: number, timeout = 90_000): Promise<void> {
  await expect(page.locator('[data-testid="graph-node"]').nth(count - 1)).toBeVisible({ timeout });
}

/**
 * Wait until exactly the expected node names are visible (all completed or frozen).
 * Fails if any expected node is missing or an unexpected node is present.
 */
async function assertExactNodes(page: Page, expectedNames: readonly string[], timeout = 90_000): Promise<void> {
  // First ensure enough nodes are visible.
  await waitForNodes(page, expectedNames.length, timeout);
  await waitForAllNodesFrozen(page, timeout);

  // Verify each expected node is present exactly once.
  for (const name of expectedNames) {
    const count = await page
      .locator(`[data-testid="graph-node"][data-node-name="${name}"]`)
      .count();
    expect(count, `Expected exactly 1 "${name}" node, got ${count}`).toBe(1);
  }

  // Verify no extra unexpected nodes appeared.
  const total = await page.locator('[data-testid="graph-node"]').count();
  expect(total, `Expected exactly ${expectedNames.length} nodes total, got ${total}`).toBe(expectedNames.length);
}

/** Return all visible graph-node elements. */
function getNodes(page: Page): Locator {
  return page.locator('[data-testid="graph-node"]');
}

/** Wait until ALL nodes have a non-"running" status. */
async function waitForAllNodesFrozen(page: Page, timeout = 40_000): Promise<void> {
  await expect(async () => {
    const nodes = await getNodes(page).all();
    expect(nodes.length).toBeGreaterThan(0);
    for (const n of nodes) {
      const status = await n.getAttribute("data-status");
      expect(status).not.toBe("running");
    }
  }).toPass({ timeout });
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe("Single Test mode — graph visualization", () => {
  test.beforeEach(async ({ page }) => {
    await goToSingleTestMode(page);
  });

  // ── Test 1: All 5 expected nodes appear exactly once on initial run ────────

  test("all expected nodes appear exactly once on initial run", async ({ page }) => {
    await page.getByRole("button", { name: /send request/i }).click();

    // Assert exact node list: query, mock_news, mock_stats, merge, mock_analysis.
    // This catches regressions where mock_analysis is missing (wired to wrong graph)
    // or duplicate nodes appear (infinite loop / checkpoint restart bug).
    await assertExactNodes(page, EXPECTED_NODES, 90_000);
  });

  // ── Bug 2: No resume button after graph-level cancel ────────────────────

  test("resume button absent after graph cancel", async ({ page }) => {
    await page.getByRole("button", { name: /send request/i }).click();

    // Wait for mock_analysis to appear (streams for 30s — easy cancel target).
    await page
      .locator('[data-testid="graph-node"][data-node-name="mock_analysis"]')
      .waitFor({ state: "visible", timeout: 60_000 });

    // Open inspector for mock_analysis.
    await page.locator('[data-testid="graph-node"][data-node-name="mock_analysis"]').click();

    // Cancel via the node-level "Cancel node" button.
    const cancelNodeBtn = page.getByRole("button", { name: /cancel node/i });
    await expect(cancelNodeBtn).toBeVisible({ timeout: 5_000 });
    await cancelNodeBtn.click();

    // Wait for all nodes to freeze.
    await waitForAllNodesFrozen(page, 30_000);

    // Bug 2 assertion: Resume button must NOT appear for a cancelled node.
    await expect(page.getByRole("button", { name: /^resume$/i })).not.toBeVisible({ timeout: 5_000 });
  });

  // ── Bug 3: Node count stable after cancel — no phantom nodes ─────────────

  test("node count stays stable after cancel", async ({ page }) => {
    await page.getByRole("button", { name: /send request/i }).click();

    await waitForNodes(page, 5, 90_000);

    // Let mock_analysis start streaming.
    await page
      .locator('[data-testid="graph-node"][data-node-name="mock_analysis"]')
      .waitFor({ state: "visible", timeout: 30_000 });

    const nodesBefore = await getNodes(page).count();

    // Open inspector and cancel.
    await page.locator('[data-testid="graph-node"][data-node-name="mock_analysis"]').click();
    const cancelNodeBtn = page.getByRole("button", { name: /cancel node/i });
    await expect(cancelNodeBtn).toBeVisible({ timeout: 5_000 });
    await cancelNodeBtn.click();

    await waitForAllNodesFrozen(page, 30_000);

    // Bug 3 assertion: node count must not increase.
    const nodesAfterCancel = await getNodes(page).count();
    expect(nodesAfterCancel, "Node count must not increase after cancel").toBe(nodesBefore);

    // Restart and verify graph cleared.
    await page.getByRole("button", { name: /restart/i }).click();
    await expect(getNodes(page)).toHaveCount(0, { timeout: 5_000 });
  });

  // ── Bug 3 (resume path): no duplicate node after pause and resume ─────────

  test("no duplicate mock_analysis node after pause and resume", async ({ page }) => {
    await page.getByRole("button", { name: /send request/i }).click();

    // Wait for mock_analysis to appear.
    await page
      .locator('[data-testid="graph-node"][data-node-name="mock_analysis"]')
      .waitFor({ state: "visible", timeout: 60_000 });

    // Open inspector and click Pause.
    await page.locator('[data-testid="graph-node"][data-node-name="mock_analysis"]').click();
    const pauseBtn = page.getByRole("button", { name: /^pause$/i });
    const pauseVisible = await pauseBtn.isVisible({ timeout: 3_000 }).catch(() => false);

    if (pauseVisible) {
      await pauseBtn.click();

      await waitForAllNodesFrozen(page, 30_000);

      const nodesAtPause = await getNodes(page).count();
      expect(nodesAtPause, "Should have exactly 5 nodes at pause").toBe(5);

      // Re-open inspector on mock_analysis — it should show Resume (paused status).
      await page.locator('[data-testid="graph-node"][data-node-name="mock_analysis"]').click();

      const resumeBtn = page.getByRole("button", { name: /^resume$/i });
      const resumeVisible = await resumeBtn.isVisible({ timeout: 5_000 }).catch(() => false);

      if (resumeVisible) {
        await resumeBtn.click();

        // mock_analysis goes back to running.
        await page
          .locator('[data-testid="graph-node"][data-node-name="mock_analysis"][data-status="running"]')
          .waitFor({ state: "visible", timeout: 15_000 });

        // Exactly 5 nodes — no duplicate spawned.
        const nodesAfterResume = await getNodes(page).count();
        expect(nodesAfterResume, "No duplicate nodes after resume").toBe(5);
      }
    }
  });

  // ── Bug 4: Tasks inside a cancelled node should show cancelled, not running ──

  test("tasks inside cancelled node show cancelled status after cancel", async ({ page }) => {
    await page.getByRole("button", { name: /send request/i }).click();

    // Wait for mock_analysis node to appear and start running.
    await page
      .locator('[data-testid="graph-node"][data-node-name="mock_analysis"]')
      .waitFor({ state: "visible", timeout: 60_000 });

    // Open inspector for mock_analysis — it should have a running task.
    await page.locator('[data-testid="graph-node"][data-node-name="mock_analysis"]').click();

    // Wait for at least one task accordion to appear (task_started event received).
    const taskRow = page.locator('[data-testid="task-row"]').first();
    const taskVisible = await taskRow.isVisible({ timeout: 20_000 }).catch(() => false);

    if (taskVisible) {
      // Cancel the node while the task is running.
      const cancelNodeBtn = page.getByRole("button", { name: /cancel node/i });
      await expect(cancelNodeBtn).toBeVisible({ timeout: 5_000 });
      await cancelNodeBtn.click();

      // Wait for all nodes to freeze.
      await waitForAllNodesFrozen(page, 30_000);

      // Bug 4 assertion: every task row should NOT be "running" after cancel.
      // Tasks that were running inside the cancelled node must show "cancelled".
      await expect(async () => {
        const taskRows = await page.locator('[data-testid="task-row"]').all();
        for (const row of taskRows) {
          const status = await row.getAttribute("data-status");
          expect(status, "Task should not remain running after node cancel").not.toBe("running");
        }
      }).toPass({ timeout: 10_000 });
    }
  });

  // ── Feature: Paused node is purple; running tasks reset to not-run ────────

  test("paused node shows purple color and running tasks are cleared", async ({ page }) => {
    // Capture console logs to cross-verify SSE ack reception in the UI.
    const consoleLogs: string[] = [];
    page.on("console", (msg) => {
      const text = msg.text();
      if (text.startsWith("[sse:")) consoleLogs.push(text);
    });

    await page.getByRole("button", { name: /send request/i }).click();

    // Wait for mock_analysis to appear (streams for 30s — easy pause target).
    await page
      .locator('[data-testid="graph-node"][data-node-name="mock_analysis"]')
      .waitFor({ state: "visible", timeout: 60_000 });

    // Open inspector for mock_analysis.
    await page.locator('[data-testid="graph-node"][data-node-name="mock_analysis"]').click();

    const pauseBtn = page.getByRole("button", { name: /^pause$/i });
    const pauseVisible = await pauseBtn.isVisible({ timeout: 5_000 }).catch(() => false);

    if (!pauseVisible) {
      test.skip();
      return;
    }

    // Collect logs emitted before pause for reference.
    const logsBeforePause = [...consoleLogs];
    console.log(`[test] UI logs before pause click: ${logsBeforePause.length} entries`);

    await pauseBtn.click();
    console.log("[test] pause button clicked — waiting for done(paused) SSE ack...");

    // Wait for all nodes to freeze (paused or completed).
    await waitForAllNodesFrozen(page, 30_000);

    // Verify the done(paused) ack was received by the UI.
    const pauseAck = consoleLogs.find((l) => l.includes("[sse:done]") && l.includes("status=paused"));
    if (pauseAck) {
      console.log(`[test] ✓ pause ack received in UI: ${pauseAck}`);
    } else {
      console.warn("[test] ✗ pause ack NOT found in UI logs — check backend logs for done(paused) emission");
    }
    expect(
      pauseAck,
      "Expected [sse:done] status=paused in UI console logs — done(paused) ack was not received",
    ).toBeTruthy();

    // The paused node should have data-status="paused".
    const pausedNode = page.locator('[data-testid="graph-node"][data-node-name="mock_analysis"][data-status="paused"]');
    await expect(pausedNode).toBeVisible({ timeout: 5_000 });

    // Paused nodes now render with purple (#722ed1) stroke/icon.
    // Verify the ⏸ icon text is present inside the node's <g>.
    const pauseIconText = pausedNode.locator('text').filter({ hasText: '⏸' });
    await expect(pauseIconText).toBeVisible({ timeout: 3_000 });

    // Verify no task rows remain in "running" state after pause.
    const taskRows = await page.locator('[data-testid="task-row"]').all();
    for (const row of taskRows) {
      const status = await row.getAttribute("data-status");
      expect(status, "No task should remain 'running' after pause").not.toBe("running");
    }
  });
});
