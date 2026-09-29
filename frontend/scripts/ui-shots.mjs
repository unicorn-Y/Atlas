// Dev helper: screenshot the running renderer (vite on :5173) in every theme.
// Usage: node frontend/scripts/ui-shots.mjs [outDir] [view...]   views: home, chat, create, code, auto, memory, skills, settings
import { chromium } from 'playwright-core';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

const out = process.argv[2] ?? 'ui-shots';
const views = process.argv.slice(3).length ? process.argv.slice(3) : ['home'];
const themes = ['light', 'aurora', 'dark'];
const NAV = { code: '项目', create: '创作', auto: '自动化', memory: '记忆', skills: '技能' };
mkdirSync(out, { recursive: true });

const browser = await chromium.launch({ channel: 'msedge', headless: true });
for (const theme of themes) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1.5 });
  await page.addInitScript((value) => localStorage.setItem('atlas.preference.appearance', value), theme);
  await page.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);
  for (const view of views) {
    if (view === 'chat') {
      const recent = page.locator('[aria-label="历史任务"] button').first();
      if (await recent.count()) { await recent.click(); await page.waitForTimeout(1200); }
    } else if (view === 'settings') {
      await page.keyboard.press('Control+,'); await page.waitForTimeout(500);
      const appearance = page.getByRole('button', { name: '外观与语音' });
      if (await appearance.count()) await appearance.click();
      await page.waitForTimeout(400);
    } else if (NAV[view]) {
      await page.getByRole('button', { name: NAV[view], exact: true }).first().click(); await page.waitForTimeout(900);
    }
    await page.screenshot({ path: join(out, `${view}-${theme}.png`) });
    if (view === 'settings') { await page.keyboard.press('Escape'); await page.waitForTimeout(300); }
  }
  await page.close();
}
await browser.close();
console.log(`saved to ${out}`);
