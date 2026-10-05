import { chromium } from 'playwright-core';
const [out, ws] = process.argv.slice(2);
const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
const page = await browser.newPage({ viewport: { width: 1500, height: 950 } });
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));
page.on('dialog', (d) => d.accept(ws));
await page.goto('http://127.0.0.1:5173'); await page.waitForTimeout(3000);
const shot = (name) => page.screenshot({ path: `${out}/${name}.png` });
const step = async (name, fn) => { try { await fn(); } catch (e) { console.log('FAIL', name, String(e).split('\n')[0].slice(0, 160)); } };

await page.keyboard.press('Control+n'); await page.waitForTimeout(800);
await page.locator('button:has(svg.lucide-folder-open)').first().click(); await page.waitForTimeout(400);
await page.getByRole('menuitem', { name: /这台电脑/ }).click(); await page.waitForTimeout(1000);
// Settings → sub-agents.
await step('settings', async () => {
  await page.getByRole('button', { name: /设置/ }).last().click(); await page.waitForTimeout(800);
  await page.getByRole('button', { name: '子 Agent' }).click(); await page.waitForTimeout(1500);
  await page.getByRole('button', { name: /^deepseek-v3$|DeepSeek V3/i }).first().click(); await page.waitForTimeout(800);
  await page.getByRole('button', { name: /深度分析/ }).click(); await page.waitForTimeout(400);
  await shot('s1-subagents');
  await page.getByRole('button', { name: '关闭设置' }).click(); await page.waitForTimeout(400);
});

// Team board.
await step('board', async () => {
  await page.getByRole('button', { name: '看板' }).first().click(); await page.waitForTimeout(1000);
  await page.getByRole('tab', { name: '团队任务' }).click(); await page.waitForTimeout(1200);
  const name = page.getByLabel('看板名称');
  if (await name.count()) { await name.fill('重构登录'); await page.getByRole('button', { name: '新建', exact: true }).click(); await page.waitForTimeout(1000); }
  for (const [title, desc, assignee, dep] of [['梳理现有登录流程', '画出现在的调用链', 'explore', ''], ['设计新的会话机制', '对比 JWT 和服务端会话', 'oracle', '梳理现有登录流程'], ['补登录测试', '覆盖密码错误和过期', 'verifier', '']]) {
    await page.getByRole('button', { name: '添加任务' }).click(); await page.waitForTimeout(300);
    await page.getByLabel('任务标题').fill(title); await page.getByLabel('任务说明').fill(desc);
    await page.getByLabel('负责的 Agent').selectOption(assignee);
    if (dep) { await page.getByRole('button', { name: /^依赖/ }).click(); await page.getByRole('checkbox', { name: dep }).check(); }
    await page.getByRole('button', { name: '添加', exact: true }).click(); await page.waitForTimeout(700);
  }
  await page.getByRole('button', { name: '「梳理现有登录流程」的操作' }).click(); await page.waitForTimeout(300);
  await page.getByRole('menuitem', { name: '完成' }).click(); await page.waitForTimeout(1200);
  await page.getByRole('button', { name: '「补登录测试」的操作' }).click(); await page.waitForTimeout(300);
  await page.getByRole('menuitem', { name: '进行中' }).click(); await page.waitForTimeout(1200);
  await shot('b1-team-board');
});

// Real runs: consultation, then parallel delegation with verification.
await step('runs', async () => {
  await page.getByRole('button', { name: '首页' }).first().click(); await page.waitForTimeout(600);
  await page.keyboard.press('Control+n'); await page.waitForTimeout(800);
  await page.locator('button:has(svg.lucide-folder-open)').first().click(); await page.waitForTimeout(400);
  await page.getByRole('menuitem', { name: /这台电脑/ }).click(); await page.waitForTimeout(1000);
  const box = page.getByLabel('消息内容');
  const wait = async (seconds) => { const before = await page.getByText(/完成，用时|没能完成/).count(); for (let i = 0; i < seconds; i++) { await page.waitForTimeout(1000); if ((await page.getByText(/完成，用时|没能完成/).count()) > before) return; } console.log('timeout'); };
  await box.fill('/moa 用一句话说说单元测试最大的价值。'); await box.press('Enter'); await wait(150);
  await box.fill('先用 todo 工具列三步计划，然后用 delegate_parallel 派两个 explore 子 Agent 并行：一个数 hello.txt 有几行，一个数 AGENTS.md 有几行；加上 verify，标准是「给出准确行数」。每完成一步更新 todo。最后用一句话汇总。'); await box.press('Enter');
  for (let i = 0; i < 40; i++) { await page.waitForTimeout(1000); if (await page.getByText(/待办 \d+\/\d+/).count()) break; }
  await shot('r1-running');
  await wait(300);
  await page.waitForTimeout(1000);
  await shot('r2-done');
  await page.getByRole('button', { name: /待办 \d+\/\d+/ }).click().catch(() => {}); await page.waitForTimeout(500);
  await page.mouse.wheel(0, -4000); await page.waitForTimeout(500);
  await shot('r3-top');
});
console.log('errors', JSON.stringify(errors.slice(0, 5)));
await browser.close();
