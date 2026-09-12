import { expect, test, type Page } from "@playwright/test";

const SERVER = "http://localhost:8123";

/** Open the app on a conversation of its own, so tests cannot see each other. */
async function open(page: Page, conversation: string) {
  await page.addInitScript((id) => {
    localStorage.setItem("tasklet-conversation", id);
  }, conversation);
  await page.goto("/");
  await expect(page.locator(".conn")).toHaveText(/open/);
}

async function ask(page: Page, text: string) {
  const box = page.getByRole("textbox");
  await box.fill(text);
  await box.press("Enter");
}

test("a run streams its tool call, answer and task list", async ({ page }) => {
  await open(page, "e2e-stream");
  await ask(page, "add a task");

  await expect(page.locator(".tool-card")).toContainText("add_task");
  await expect(page.locator(".tool-card.tool-done")).toBeVisible();
  await expect(page.locator(".messages")).toContainText("done.");
  await expect(page.locator(".task-items li")).toHaveText(/Ship v2/);
  await expect(page.locator(".task-count")).toContainText("1 total");
});

test("a destructive tool waits for approval, then runs", async ({ page }) => {
  await open(page, "e2e-approve");
  await ask(page, "add a task");
  await expect(page.locator(".task-items li")).toHaveCount(1);

  await ask(page, "delete the first task");
  const card = page.locator(".approval-card");
  await expect(card).toBeVisible();
  await expect(card).toContainText("approval required");
  // Not run yet: the list is untouched while the run is paused.
  await expect(page.locator(".task-items li")).toHaveCount(1);

  await card.getByRole("button", { name: "Approve" }).click();
  await expect(page.locator(".approval-verdict")).toContainText("Approved");
  await expect(page.locator(".task-empty")).toBeVisible();
});

test("denying leaves the task alone", async ({ page }) => {
  await open(page, "e2e-deny");
  await ask(page, "add a task");
  await expect(page.locator(".task-items li")).toHaveCount(1);

  await ask(page, "delete the first task");
  await page
    .locator(".approval-card")
    .getByRole("button", { name: "Deny" })
    .click();

  await expect(page.locator(".approval-verdict")).toContainText("Denied");
  await expect(page.locator(".task-items li")).toHaveCount(1);
});

test("both tabs on a conversation follow the same run", async ({ browser }) => {
  const context = await browser.newContext();
  const first = await context.newPage();
  const second = await context.newPage();

  await open(first, "e2e-tabs");
  await open(second, "e2e-tabs");

  await ask(first, "add a task");

  // The second tab never sent anything, yet sees the run and the new state.
  await expect(second.locator(".tool-card")).toContainText("add_task");
  await expect(second.locator(".task-items li")).toHaveText(/Ship v2/);
  await expect(first.locator(".task-items li")).toHaveText(/Ship v2/);

  await context.close();
});

test("a tab joining mid-run is replayed from the start", async ({
  browser,
}) => {
  const context = await browser.newContext();
  const first = await context.newPage();
  await open(first, "e2e-replay");

  await ask(first, "add a task");
  await expect(first.locator(".task-items li")).toHaveCount(1);

  // A fresh tab has no history of its own: what it shows came from the server.
  const late = await context.newPage();
  await open(late, "e2e-replay");
  await expect(late.locator(".task-items li")).toHaveText(/Ship v2/);

  await context.close();
});

test("an http notification reaches the browser", async ({ page, request }) => {
  await open(page, "e2e-notify");

  const response = await request.post(
    `${SERVER}/conversations/e2e-notify/notify`,
    { data: { title: "Deploy", body: "shipped from curl" } },
  );
  expect(response.ok()).toBeTruthy();

  await expect(page.locator(".toast")).toContainText("shipped from curl");
});

test("a reminder tool notifies the conversation back", async ({ page }) => {
  await open(page, "e2e-remind");
  await ask(page, "remind me to stretch");

  await expect(page.locator(".toast")).toContainText("stretch");
});
