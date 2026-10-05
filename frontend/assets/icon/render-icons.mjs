// Run from the repo root: node frontend/assets/icon/render-icons.mjs
// Renders icon.svg (>=48px) and icon-small.svg (<=32px) with Edge, then packs icon.ico
// (PNG-compressed entries, supported since Windows Vista) and icon.png (512px).
import { chromium } from 'playwright-core';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = path.dirname(fileURLToPath(import.meta.url));
const edge = process.env.EDGE_PATH ?? 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const sizes = [16, 24, 32, 48, 64, 128, 256];
const browser = await chromium.launch({ executablePath: edge, headless: true });
const page = await browser.newPage();
async function render(file, size) {
  const svg = fs.readFileSync(path.join(dir, file), 'utf8');
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(`<html><body style="margin:0;background:transparent">${svg.replace('<svg ', `<svg width="${size}" height="${size}" `)}</body></html>`);
  return page.screenshot({ omitBackground: true, clip: { x: 0, y: 0, width: size, height: size } });
}
const pngs = [];
for (const size of sizes) pngs.push({ size, data: await render(size <= 32 ? 'icon-small.svg' : 'icon.svg', size) });
fs.writeFileSync(path.join(dir, 'icon.png'), await render('icon.svg', 512));
await browser.close();

const header = Buffer.alloc(6);
header.writeUInt16LE(0, 0); header.writeUInt16LE(1, 2); header.writeUInt16LE(pngs.length, 4);
const entries = []; let offset = 6 + 16 * pngs.length;
for (const { size, data } of pngs) {
  const e = Buffer.alloc(16);
  e.writeUInt8(size >= 256 ? 0 : size, 0); e.writeUInt8(size >= 256 ? 0 : size, 1);
  e.writeUInt8(0, 2); e.writeUInt8(0, 3); e.writeUInt16LE(1, 4); e.writeUInt16LE(32, 6);
  e.writeUInt32LE(data.length, 8); e.writeUInt32LE(offset, 12);
  offset += data.length; entries.push(e);
}
fs.writeFileSync(path.join(dir, 'icon.ico'), Buffer.concat([header, ...entries, ...pngs.map((p) => p.data)]));
console.log('wrote icon.ico', sizes.join(','), 'and icon.png 512');
