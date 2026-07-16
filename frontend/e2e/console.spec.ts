import { expect, test, type Browser, type BrowserContextOptions, type Page } from '@playwright/test';

const CONSOLE_ORIGIN = 'http://127.0.0.1:8790';
const FAKE_STATE_URL = 'http://127.0.0.1:9877/test/state';

async function openConsole(
  browser: Browser,
  options: BrowserContextOptions = {},
  observePage?: (page: Page) => void,
) {
  const context = await browser.newContext(options);
  await context.grantPermissions(['microphone'], { origin: CONSOLE_ORIGIN });
  const page = await context.newPage();
  observePage?.(page);
  await page.goto('/');
  await expect(page.getByLabel('Message to agent')).toBeVisible();
  await expect(page.getByLabel('Message to agent')).toBeEnabled();
  await expect(page.locator('[data-console-shell]')).toHaveCount(1);
  return { context, page };
}

async function submit(page: Page, text: string) {
  const composer = page.getByLabel('Message to agent');
  await composer.fill(text);
  await composer.press('Enter');
  await expect(page.locator('.message.user').filter({ hasText: text })).toBeVisible();
}

test.describe.configure({ mode: 'serial' });

test('presents the Hermes research-console identity at desktop and mobile sizes', async ({ browser }) => {
  const desktop = await openConsole(browser, { viewport: { width: 1440, height: 1000 } });
  await expect(desktop.page.locator('.hermes-mark')).toBeVisible();
  await expect(desktop.page.getByRole('heading', { name: 'Voice Console' })).toBeVisible();
  await expect(desktop.page.getByLabel('Agent model roles')).toContainText('GPT-Realtime 2.1');
  await expect(desktop.page.getByLabel('Agent model roles')).toContainText('GPT-5.6');
  const desktopVisuals = await desktop.page.evaluate(() => {
    const heading = document.querySelector<HTMLElement>('.hero h1');
    const card = document.querySelector<HTMLElement>('.card');
    const root = getComputedStyle(document.documentElement);
    const luminance = (value: string) => {
      const channels = value.match(/[0-9a-f]{2}/gi)?.map((channel) => parseInt(channel, 16) / 255) ?? [];
      const linear = channels.map((channel) => channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4);
      return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2];
    };
    const operational = root.getPropertyValue('--operational-muted').trim();
    const surface = root.getPropertyValue('--surface-solid').trim();
    const lighter = Math.max(luminance(operational), luminance(surface));
    const darker = Math.min(luminance(operational), luminance(surface));
    return {
      headingFamily: heading ? getComputedStyle(heading).fontFamily : '',
      cardBorder: card ? getComputedStyle(card).borderTopStyle : '',
      operationalContrast: (lighter + .05) / (darker + .05),
      overflow: document.documentElement.scrollWidth <= window.innerWidth,
    };
  });
  expect(desktopVisuals.headingFamily).toContain('Iowan Old Style');
  expect(desktopVisuals.cardBorder).toBe('solid');
  expect(desktopVisuals.operationalContrast).toBeGreaterThanOrEqual(5);
  expect(desktopVisuals.overflow).toBe(true);
  await desktop.context.close();

  const mobile = await openConsole(browser, { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  await expect(mobile.page.locator('.hermes-mark-mobile')).toBeVisible();
  const recordBounds = await mobile.page.getByRole('button', { name: 'Start recording' }).boundingBox();
  expect(recordBounds).not.toBeNull();
  expect(recordBounds!.width).toBeGreaterThanOrEqual(44);
  expect(recordBounds!.height).toBeGreaterThanOrEqual(44);
  expect(await mobile.page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await mobile.context.close();
});

test('renders the intended desktop, compact, and mobile shells without overflow', async ({ browser }) => {
  for (const viewport of [{ width: 1440, height: 900 }, { width: 1280, height: 800 }]) {
    const { context, page } = await openConsole(browser, { viewport });
    await expect(page.locator('[data-console-shell="desktop"]')).toBeVisible();
    await expect(page.locator('.desktop-inspector')).toBeVisible();
    await expect(page.locator('.compact-inspector')).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await context.close();
  }

  const compact = await openConsole(browser, { viewport: { width: 1024, height: 768 } });
  await expect(compact.page.locator('[data-console-shell="desktop"]')).toBeVisible();
  await expect(compact.page.locator('.compact-inspector')).toBeVisible();
  await expect(compact.page.locator('.desktop-inspector')).toHaveCount(0);
  await compact.page.locator('.compact-inspector > summary').click();
  await expect(compact.page.getByTestId('run-inspector')).toBeVisible();
  await compact.context.close();

  for (const viewport of [{ width: 390, height: 844 }, { width: 844, height: 390 }]) {
    const mobile = await openConsole(browser, { viewport, isMobile: true, hasTouch: true });
    await expect(mobile.page.locator('[data-console-shell="mobile"]')).toBeVisible();
    await expect(mobile.page.getByRole('button', { name: 'Start recording' })).toBeVisible();
    await expect(mobile.page.getByText('Spoken replies use an AI-generated voice.').first()).toBeVisible();
    const dock = await mobile.page.locator('.mobile-composer-dock').boundingBox();
    expect(dock).not.toBeNull();
    expect(dock!.x).toBeGreaterThanOrEqual(0);
    expect(dock!.x + dock!.width).toBeLessThanOrEqual(viewport.width + 1);
    expect(dock!.y + dock!.height).toBeLessThanOrEqual(viewport.height + 1);
    expect(await mobile.page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await mobile.context.close();
  }
});

test('shows tool calls in the conversation and persists the actual conversation', async ({ browser }) => {
  const { context, page } = await openConsole(browser, { viewport: { width: 1440, height: 900 } });
  const prompt = 'phase nine tool display';
  await submit(page, prompt);

  const toolCard = page.locator('.message.tool').filter({ hasText: 'fake_tool' });
  await expect(toolCard).toBeVisible();
  await expect(toolCard).toContainText('deterministic fake target');
  await expect(toolCard.getByRole('status')).toContainText('completed');
  await expect(toolCard.getByRole('status')).toContainText('0.00s');
  await expect(page.locator('.message.assistant').filter({ hasText: `Fake response to: ${prompt}` })).toBeVisible();
  await expect(page.getByRole('status').first()).toHaveText(/completed|ready/);
  await expect(page.locator('.timeline')).toContainText('agent.tool.started');
  await expect(page.locator('.timeline')).toContainText('agent.tool.completed');
  await page.getByRole('button', { name: 'Cancel speech' }).click();

  const failedPrompt = 'failed tool display probe';
  await submit(page, failedPrompt);
  const failedTool = page.locator('.message.tool').filter({ hasText: 'fake_tool' }).last();
  await expect(failedTool.getByRole('status')).toContainText('failed');
  await expect(page.locator('.message.assistant').filter({ hasText: `Fake response to: ${failedPrompt}` })).toBeVisible();

  await page.reload();
  await expect(page.getByLabel('Message to agent')).toBeVisible();
  await expect(page.locator('.message.user').filter({ hasText: prompt })).toBeVisible();
  await expect(page.locator('.message.assistant').filter({ hasText: `Fake response to: ${prompt}` })).toBeVisible();
  await context.close();
});

test('contains approval focus and stores only expiring recovery metadata', async ({ browser }) => {
  const { context, page } = await openConsole(browser, { viewport: { width: 1280, height: 800 } });
  const prompt = 'approval browser safety probe';
  await submit(page, prompt);

  const dialog = page.getByRole('dialog', { name: 'Hermes approval request' });
  await expect(dialog).toBeVisible();
  const deny = dialog.getByRole('button', { name: 'Deny' });
  await expect(deny).toBeFocused();
  await expect(dialog).toContainText('/tmp/browser-acceptance/');
  expect(await dialog.evaluate((element) => element.scrollHeight <= element.clientHeight || getComputedStyle(element).overflowY === 'auto')).toBe(true);

  const storage = await page.evaluate(() => {
    const entries: Record<string, string> = {};
    for (let index = 0; index < sessionStorage.length; index += 1) {
      const key = sessionStorage.key(index);
      if (key) entries[key] = sessionStorage.getItem(key) ?? '';
    }
    return entries;
  });
  expect(Object.keys(storage)).toEqual(['hvc.recovery.v1']);
  const recovery = JSON.parse(storage['hvc.recovery.v1']) as Record<string, unknown>;
  expect(Object.keys(recovery).sort()).toEqual([
    'conversationId', 'expiresAt', 'lastSequence', 'runId', 'savedAt', 'target', 'version',
  ]);
  expect(Number(recovery.expiresAt)).toBeGreaterThan(Date.now());
  expect(JSON.stringify(recovery)).not.toContain(prompt);
  expect(await page.evaluate(() => localStorage.length)).toBe(0);
  await expect(dialog.getByRole('button', { name: 'Permanently allow' })).toHaveCount(0);

  await dialog.locator('summary').focus();
  await page.keyboard.press('Shift+Tab');
  await expect(deny).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeVisible();
  await expect(deny).toBeFocused();
  await deny.press('Enter');
  await expect(dialog).toHaveCount(0);
  await expect(page.getByLabel('Message to agent')).toBeFocused();
  await expect(page.locator('.message.assistant').filter({ hasText: `Fake response to: ${prompt}` })).toBeVisible();
  await context.close();

  const mobile = await openConsole(browser, { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const mobilePrompt = 'approval mobile containment probe';
  await submit(mobile.page, mobilePrompt);
  const mobileDialog = mobile.page.getByRole('dialog', { name: 'Hermes approval request' });
  await expect(mobileDialog).toBeVisible();
  await expect(mobileDialog).toContainText('/tmp/browser-acceptance/');
  await expect(mobileDialog.getByRole('button', { name: 'Deny' })).toBeFocused();
  await mobileDialog.getByRole('button', { name: 'Deny' }).click();
  await expect(mobileDialog).toHaveCount(0);
  await mobile.context.close();
});

test('keeps one socket and run across layout changes, reconnects, reconciles, and stops', async ({ browser, request }) => {
  const beforeResponse = await request.get(FAKE_STATE_URL, { headers: { Authorization: 'Bearer fake' } });
  expect(beforeResponse.ok()).toBe(true);
  const before = await beforeResponse.json() as { run_count: number };

  let sockets = 0;
  const { context, page } = await openConsole(
    browser,
    { viewport: { width: 800, height: 900 } },
    (observedPage) => observedPage.on('websocket', () => { sockets += 1; }),
  );
  const layoutPrompt = 'slow run layout continuity probe';
  await submit(page, layoutPrompt);
  await expect(page.locator('.message.tool').filter({ hasText: 'fake_tool' })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator('[data-console-shell]')).toHaveCount(1);
  await expect(page.locator('[data-console-shell="mobile"]')).toBeVisible();
  await expect(page.locator('.message.user').filter({ hasText: layoutPrompt })).toBeVisible();
  expect(sockets).toBe(1);
  await page.getByText('Activity and diagnostics').click();
  const mobileStop = page.getByRole('button', { name: 'Stop run' });
  await expect(mobileStop).toBeEnabled();
  await mobileStop.click();
  await expect(mobileStop).toBeDisabled();

  await page.setViewportSize({ width: 1280, height: 800 });
  await expect(page.locator('[data-console-shell="desktop"]')).toBeVisible();
  const recoveryPrompt = 'slow run recovery probe';
  await submit(page, recoveryPrompt);
  await expect(page.locator('.message.tool').filter({ hasText: 'fake_tool' }).last()).toBeVisible();
  await expect.poll(async () => page.evaluate(() => sessionStorage.getItem('hvc.recovery.v1'))).not.toBeNull();
  await page.reload();
  await expect(page.getByLabel('Message to agent')).toBeVisible();
  await expect(page.locator('.message.assistant').filter({ hasText: `Fake response to: ${recoveryPrompt}` })).toBeVisible();

  const reconcilePrompt = 'drop sse reconciliation probe';
  await submit(page, reconcilePrompt);
  await expect(page.locator('.message.assistant').filter({ hasText: `Fake response to: ${reconcilePrompt}` })).toBeVisible();

  const afterResponse = await request.get(FAKE_STATE_URL, { headers: { Authorization: 'Bearer fake' } });
  const after = await afterResponse.json() as { run_count: number };
  expect(after.run_count).toBe(before.run_count + 3);
  await context.close();
});

test('recovers a run when the browser disconnects before receiving the run id', async ({ browser, request }) => {
  const beforeResponse = await request.get(FAKE_STATE_URL, { headers: { Authorization: 'Bearer fake' } });
  const before = await beforeResponse.json() as { run_count: number };
  const { context, page } = await openConsole(browser, { viewport: { width: 1280, height: 800 } });
  const prompt = 'delayed acceptance slow run pre-id disconnect probe';
  await submit(page, prompt);
  await page.close();
  await new Promise((resolve) => setTimeout(resolve, 1_000));

  const recoveredPage = await context.newPage();
  await recoveredPage.goto('/');
  await expect(recoveredPage.getByLabel('Message to agent')).toBeEnabled();
  await expect(recoveredPage.locator('.message.assistant').filter({ hasText: `Fake response to: ${prompt}` })).toBeVisible();
  const afterResponse = await request.get(FAKE_STATE_URL, { headers: { Authorization: 'Bearer fake' } });
  const after = await afterResponse.json() as { run_count: number };
  expect(after.run_count).toBe(before.run_count + 1);
  await context.close();
});

test('supports tap-to-record and handles denied microphone permission', async ({ browser }) => {
  const voice = await openConsole(browser, { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const record = voice.page.getByRole('button', { name: 'Start recording' });
  await record.click();
  await expect(voice.page.getByRole('button', { name: 'Send recording' })).toBeVisible();
  await voice.page.waitForTimeout(700);
  await voice.page.getByRole('button', { name: 'Send recording' }).click();
  await expect(voice.page.locator('.message.user').filter({ hasText: 'browser microphone turn' })).toBeVisible();
  await expect(voice.page.locator('.message.assistant').filter({ hasText: 'Fake response to: browser microphone turn' })).toBeVisible();

  await voice.page.getByRole('button', { name: 'Start recording' }).click();
  await expect(voice.page.getByRole('button', { name: 'Send recording' })).toBeVisible();
  await voice.page.setViewportSize({ width: 844, height: 390 });
  await expect(voice.page.locator('[data-console-shell="mobile"]')).toBeVisible();
  await voice.page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect(voice.page.getByRole('button', { name: 'Start recording' })).toBeVisible();
  await voice.context.close();

  const deniedContext = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const deniedPage = await deniedContext.newPage();
  await deniedPage.addInitScript(() => {
    Object.defineProperty(navigator.mediaDevices, 'getUserMedia', {
      configurable: true,
      value: async () => { throw new DOMException('Microphone permission denied for browser test', 'NotAllowedError'); },
    });
  });
  await deniedPage.goto('/');
  await expect(deniedPage.getByLabel('Message to agent')).toBeVisible();
  await deniedPage.getByRole('button', { name: 'Start recording' }).click();
  await expect(deniedPage.locator('.error')).toContainText('Microphone permission denied for browser test');
  await expect(deniedPage.getByLabel('Message to agent')).toBeEnabled();
  await deniedContext.close();
});

test('honors reduced motion and forced colors while retaining semantic controls', async ({ browser }) => {
  const { context, page } = await openConsole(browser, {
    viewport: { width: 1280, height: 800 },
    reducedMotion: 'reduce',
    forcedColors: 'active',
  });
  expect(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)).toBe(true);
  expect(await page.evaluate(() => matchMedia('(forced-colors: active)').matches)).toBe(true);
  await expect(page.getByRole('status').first()).toBeAttached();
  await expect(page.getByRole('button', { name: 'Send' })).toHaveCSS('border-top-style', 'solid');
  await page.getByLabel('Message to agent').focus();
  await expect(page.getByLabel('Message to agent')).toBeFocused();
  await context.close();
});
