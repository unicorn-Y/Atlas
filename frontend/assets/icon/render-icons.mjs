// Run from the repo root: node frontend/assets/icon/render-icons.mjs
// Renders the Atlas icon in each theme's palette with Edge:
//   icon-<theme>.png (256px)  — the running window/taskbar icon, swapped when the theme changes
//   icon.ico + icon.png        — the static exe/shortcut icon (夜航 palette: readable on any wallpaper)
// icon.svg is used from 48px up, icon-small.svg (bolder, fewer rings) for 16–32px.
import { chromium } from 'playwright-core';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = path.dirname(fileURLToPath(import.meta.url));
const edge = process.env.EDGE_PATH ?? 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';

// Palettes follow the themes in src/renderer/styles/app.css (--mark-*, --core-*, --bg).
const PALETTES = {
  dark: { // 夜航: night tile, brass
    bg1: '#1D2738', bg2: '#0E131D', bg3: '#06080C',
    m1: '#F7DCA2', m2: '#D3A055', m3: '#8A5E22',
    c1: '#FFF4D6', c2: '#F0C878', c3: '#9C6B27',
    g1: '#F6CF84', g2: '#E0A84E', star: '#F3DDAE', hi: '#FFFBEE',
  },
  light: { // 白瓷: porcelain tile, deeper brass for contrast on white
    bg1: '#FFFFFF', bg2: '#F6F4EF', bg3: '#E4E0D7',
    m1: '#D9A75A', m2: '#A9762F', m3: '#6E4A17',
    c1: '#FFF1CC', c2: '#E2B062', c3: '#8E5F1F',
    g1: '#E9C27A', g2: '#C8964A', star: '#B08A4E', hi: '#FFFFFF',
  },
  aurora: { // 晨光: lavender dawn tile, periwinkle rings
    bg1: '#FBF8FF', bg2: '#ECE8FC', bg3: '#D6DAF8',
    m1: '#A9B3FF', m2: '#7380F2', m3: '#4248C2',
    c1: '#FFF0FA', c2: '#C7B8FF', c3: '#6B70E8',
    g1: '#C9B8FF', g2: '#8E9BFA', star: '#8E9BFA', hi: '#FFFFFF',
  },
};

const fill = (file, palette) => fs.readFileSync(path.join(dir, file), 'utf8')
  .replace(/\{\{(\w+)\}\}/g, (_m, key) => palette[key]);

const browser = await chromium.launch({ executablePath: edge, headless: true });
const page = await browser.newPage();
async function render(svg, size) {
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(`<html><body style="margin:0;background:transparent">${svg.replace('<svg ', `<svg width="${size}" height="${size}" `)}</body></html>`);
  return page.screenshot({ omitBackground: true, clip: { x: 0, y: 0, width: size, height: size } });
}

for (const [theme, palette] of Object.entries(PALETTES)) {
  fs.writeFileSync(path.join(dir, `icon-${theme}.png`), await render(fill('icon.svg', palette), 256));
}

const sizes = [16, 24, 32, 48, 64, 128, 256];
const pngs = [];
for (const size of sizes) {
  pngs.push({ size, data: await render(fill(size <= 32 ? 'icon-small.svg' : 'icon.svg', PALETTES.dark), size) });
}
fs.writeFileSync(path.join(dir, 'icon.png'), await render(fill('icon.svg', PALETTES.dark), 512));
await browser.close();

// ICO with PNG-compressed entries (supported since Windows Vista).
const header = Buffer.alloc(6);
header.writeUInt16LE(0, 0); header.writeUInt16LE(1, 2); header.writeUInt16LE(pngs.length, 4);
const entries = [];
let offset = 6 + 16 * pngs.length;
for (const { size, data } of pngs) {
  const entry = Buffer.alloc(16);
  entry.writeUInt8(size >= 256 ? 0 : size, 0); entry.writeUInt8(size >= 256 ? 0 : size, 1);
  entry.writeUInt16LE(1, 4); entry.writeUInt16LE(32, 6);
  entry.writeUInt32LE(data.length, 8); entry.writeUInt32LE(offset, 12);
  offset += data.length;
  entries.push(entry);
}
fs.writeFileSync(path.join(dir, 'icon.ico'), Buffer.concat([header, ...entries, ...pngs.map((p) => p.data)]));
console.log(`wrote icon-{${Object.keys(PALETTES).join(',')}}.png, icon.ico (${sizes.join(',')}), icon.png`);
