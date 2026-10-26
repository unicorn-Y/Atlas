import fs from 'node:fs';
import zlib from 'node:zlib';

function crc32(buffer) {
  let crc = 0xffffffff;
  for (const byte of buffer) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(name, data) {
  const type = Buffer.from(name);
  const length = Buffer.alloc(4); length.writeUInt32BE(data.length);
  const checksum = Buffer.alloc(4); checksum.writeUInt32BE(crc32(Buffer.concat([type, data])));
  return Buffer.concat([length, type, data, checksum]);
}

function makePng(size) {
  const rows = Buffer.alloc((size * 4 + 1) * size);
  const bg = [55, 88, 214, 255];
  const pattern = ['01110', '10001', '10001', '11111', '10001', '10001', '10001'];
  const unit = size / 10;
  const startX = Math.round((size - 5 * unit) / 2);
  const startY = Math.round((size - 7 * unit) / 2);
  for (let y = 0; y < size; y += 1) {
    const row = y * (size * 4 + 1); rows[row] = 0;
    for (let x = 0; x < size; x += 1) {
      const patternX = Math.floor((x - startX) / unit);
      const patternY = Math.floor((y - startY) / unit);
      const white = patternY >= 0 && patternY < pattern.length && patternX >= 0 && patternX < 5
        && pattern[patternY][patternX] === '1';
      const offset = row + 1 + x * 4;
      rows[offset] = white ? 255 : bg[0]; rows[offset + 1] = white ? 255 : bg[1];
      rows[offset + 2] = white ? 255 : bg[2]; rows[offset + 3] = 255;
    }
  }
  const header = Buffer.alloc(13); header.writeUInt32BE(size, 0); header.writeUInt32BE(size, 4);
  header[8] = 8; header[9] = 6;
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk('IHDR', header), chunk('IDAT', zlib.deflateSync(rows)), chunk('IEND', Buffer.alloc(0)),
  ]);
}

for (const size of [32, 80]) fs.writeFileSync(`icon-${size}.png`, makePng(size));
