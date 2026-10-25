import { mkdir, readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import readline from 'node:readline';
import makeWASocket, { DisconnectReason, downloadMediaMessage, useMultiFileAuthState } from '@whiskeysockets/baileys';
import pino from 'pino';

const authDir = path.resolve(process.argv[2]);
await mkdir(authDir, { recursive: true });
const emit = (value) => process.stdout.write(`${JSON.stringify(value)}\n`);
let socket;
let stopped = false;
let reconnectTimer;
const logger = pino({ level: 'silent' });
const maxMediaBytes = 20 * 1024 * 1024;

async function connect() {
  const { state, saveCreds } = await useMultiFileAuthState(authDir);
  socket = makeWASocket({ auth: state, printQRInTerminal: false, logger });
  socket.ev.on('creds.update', saveCreds);
  socket.ev.on('connection.update', ({ connection, lastDisconnect, qr }) => {
    if (qr) emit({ type: 'qr', value: qr });
    if (connection) emit({ type: 'connection', state: connection });
    if (connection === 'close' && !stopped) {
      const status = lastDisconnect?.error?.output?.statusCode;
      if (status === DisconnectReason.loggedOut) emit({ type: 'connection', state: 'logged_out' });
      else reconnectTimer = setTimeout(() => void connect().catch((error) => emit({ type: 'error', message: String(error.message || error) })), 1500);
    }
  });
  socket.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return;
    for (const message of messages) {
      if (!message?.key?.remoteJid || message.key.fromMe) continue;
      const body = message.message ?? {};
      const wrapped = body.ephemeralMessage?.message ?? body;
      const messageType = Object.keys(wrapped).find((key) => /Message$/.test(key) && key !== 'protocolMessage') || '';
      const media = wrapped[messageType];
      const text = wrapped.conversation || wrapped.extendedTextMessage?.text || media?.caption || '';
      let attachment;
      if (media && /^(image|video|audio|document|sticker)Message$/.test(messageType)) {
        try {
          const buffer = await downloadMediaMessage(message, 'buffer', {}, { logger, reuploadRequest: socket.updateMediaMessage });
          if (buffer.length <= maxMediaBytes) attachment = { data: buffer.toString('base64'), mime_type: media.mimetype || 'application/octet-stream', filename: media.fileName || '', kind: messageType.replace('Message', '') };
          else emit({ type: 'warning', message: '忽略超过 20 MiB 的 WhatsApp 附件' });
        } catch (error) { emit({ type: 'warning', message: `WhatsApp 附件读取失败：${String(error.message || error)}` }); }
      }
      emit({ type: 'message', value: {
        event_id: message.key.id || `${message.key.remoteJid}:${message.messageTimestamp || Date.now()}`,
        chat_id: message.key.remoteJid,
        sender_id: message.key.participant || message.key.remoteJid,
        sender_name: message.pushName || '',
        is_group: message.key.remoteJid.endsWith('@g.us'),
        is_mention: Boolean(wrapped.extendedTextMessage?.contextInfo?.mentionedJid?.includes(socket.user?.id?.split(':')[0] + '@s.whatsapp.net')),
        mentioned_jid: wrapped.extendedTextMessage?.contextInfo?.mentionedJid || [],
        reply_to_event_id: String(wrapped.extendedTextMessage?.contextInfo?.stanzaId || ''),
        text,
        timestamp: Number(message.messageTimestamp || Date.now() / 1000),
        attachment,
      } });
    }
  });
}

async function request(command) {
  const id = String(command.id || '');
  if (!id) throw new Error('request id is required');
  if (command.op === 'send') {
    const jid = command.chat_id;
    if (!jid || !/^[^\s@]+@(s\.whatsapp\.net|g\.us)$/.test(jid)) throw new Error('chat_id must be a WhatsApp user or group JID');
    const attachment = command.attachment;
    let content = { text: command.text || '' };
    if (attachment?.path) {
      const file = path.resolve(attachment.path);
      const metadata = await stat(file);
      if (!metadata.isFile() || metadata.size > maxMediaBytes) throw new Error('WhatsApp attachment must be a file no larger than 20 MiB');
      const data = await readFile(file);
      const mime = attachment.mime_type || 'application/octet-stream';
      const kind = mime.startsWith('image/') ? 'image' : mime.startsWith('video/') ? 'video' : mime.startsWith('audio/') ? 'audio' : 'document';
      content = { [kind]: data, mimetype: mime, ...(kind === 'document' ? { fileName: attachment.filename || path.basename(file) } : {}), ...(command.text ? { caption: command.text } : {}) };
    }
    const result = await socket.sendMessage(jid, content, command.reply_to ? { quoted: { key: { remoteJid: jid, id: command.reply_to, fromMe: false }, message: { conversation: '' } } } : {});
    emit({ type: 'response', id, value: { message_id: result?.key?.id || '' } });
    return;
  }
  throw new Error('unknown bridge operation');
}

const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
input.on('line', (line) => {
  let command;
  try { command = JSON.parse(line); } catch { emit({ type: 'error', message: 'invalid JSON request' }); return; }
  void request(command).catch((error) => emit({ type: 'response', id: String(command.id || ''), error: String(error.message || error) }));
});
await connect();
input.on('close', async () => { stopped = true; clearTimeout(reconnectTimer); await socket?.end(undefined); process.exit(0); });
