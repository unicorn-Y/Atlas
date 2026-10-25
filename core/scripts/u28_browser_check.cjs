const { chromium } = require('playwright');

async function main() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    args: ['--no-sandbox'],
  });
  try {
    const page = await browser.newPage();
    await page.route('http://127.0.0.1:8765/api/workspace/file**', async route => {
      const path = new URL(route.request().url()).searchParams.get('path') || '';
      const content = path.includes('second') ? '# U28 second preview' : '# U28 first preview';
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ path, content, binary: false, truncated: false }) });
    });
    await page.goto('http://127.0.0.1:5173', { waitUntil: 'domcontentloaded' });
    await page.evaluate(async () => {
      const ReactModule = await import('/node_modules/.vite/deps/react.js');
      const React = ReactModule.default;
      const ReactDOMModule = await import('/node_modules/.vite/deps/react-dom_client.js');
      const ReactDOM = ReactDOMModule.default;
      const FilesPanel = (await import('/src/renderer/shell/panels/FilesPanel.tsx')).default;
      const CanvasPanel = (await import('/src/renderer/shell/panels/AgentCanvasPanel.tsx')).default;
      const rootNode = document.createElement('div');
      rootNode.id = 'u28-check-root';
      Object.assign(rootNode.style, { position: 'fixed', inset: '0', zIndex: '999999', background: 'white', color: 'black' });
      document.body.append(rootNode);
      const root = ReactDOM.createRoot(rootNode);
      const renderFiles = path => root.render(React.createElement(FilesPanel, {
        workspace: 'C:/u28-fixture', onChooseWorkspace: () => {}, refreshKey: 'u28', onPreview: () => {},
        previewOnly: true, previewPath: path,
      }));
      window.__u28 = { React, root, renderFiles, CanvasPanel };
      renderFiles('first.md');
    });
    await page.getByText('U28 first preview', { exact: false }).waitFor({ timeout: 15000 });
    await page.evaluate(() => window.__u28.renderFiles('second.md'));
    await page.getByText('U28 second preview', { exact: false }).waitFor({ timeout: 10000 });
    await page.getByRole('button', { name: '返回上一个预览文件' }).click();
    await page.getByText('U28 first preview', { exact: false }).waitFor({ timeout: 10000 });
    await page.getByRole('button', { name: '前进到下一个预览文件' }).click();
    await page.getByText('U28 second preview', { exact: false }).waitFor({ timeout: 10000 });
    const previewText = await page.locator('#u28-check-root').innerText();
    if (!previewText.includes('second preview') || !(await page.getByRole('group', { name: '显示方式' }).count())) throw new Error(`standalone file preview/source controls failed: ${previewText.slice(0, 600)}`);

    await page.evaluate(() => {
      const { React, root, CanvasPanel } = window.__u28;
      const event = (format, content, mode = 'replace') => ({ type: 'canvas.update', data: { widget_id: 'table', title: 'U28 table', format, content, mode } });
      root.render(React.createElement(CanvasPanel, { events: [event('table', JSON.stringify({ columns: ['Name'], rows: [['Atlas']] }))] }));
    });
    await page.getByRole('cell', { name: 'Atlas' }).waitFor({ timeout: 10000 });
    await page.evaluate(() => {
      const { React, root, CanvasPanel } = window.__u28;
      const event = (format, content, mode = 'replace') => ({ type: 'canvas.update', data: { widget_id: 'html', title: 'U28 HTML', format, content, mode } });
      root.render(React.createElement(CanvasPanel, { events: [event('html', '<h1>Safe canvas preview</h1>')] }));
    });
    await page.locator('#u28-check-root iframe[title="共享画布：U28 HTML"]').waitFor({ timeout: 10000 });
    const sandbox = await page.locator('#u28-check-root iframe[title="共享画布：U28 HTML"]').getAttribute('sandbox');
    if (sandbox !== '') throw new Error('shared HTML canvas iframe must have an empty sandbox');
    await page.evaluate(() => {
      const { React, root, CanvasPanel } = window.__u28;
      const events = [
        { type: 'canvas.update', data: { widget_id: 'append', title: 'U28 append', format: 'mermaid', mode: 'replace', content: 'graph TD; A-->B' } },
        { type: 'canvas.update', data: { widget_id: 'append', title: 'U28 append', format: 'mermaid', mode: 'append', content: '; B-->C' } },
      ];
      root.render(React.createElement(CanvasPanel, { events }));
    });
    await page.locator('#u28-check-root pre').filter({ hasText: 'graph TD; A-->B; B-->C' }).waitFor({ state: 'attached', timeout: 10000 });
    console.log('CHROME PREVIEW HISTORY AND SHARED CANVAS PASS');
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
