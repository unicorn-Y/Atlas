import { appendFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const moduleDir = path.dirname(fileURLToPath(import.meta.url));

function atlasLogPath(): string {
  const dataRoot = process.env.ATLAS_DATA_DIR
    ? path.resolve(process.env.ATLAS_DATA_DIR)
    : process.env.ATLAS_ROOT
      ? path.resolve(process.env.ATLAS_ROOT)
      : process.env.ATLAS_LOG_ROOT
        ? path.resolve(process.env.ATLAS_LOG_ROOT)
        : path.resolve(moduleDir, '../../..');
  return path.join(dataRoot, 'data', 'logs', 'backend-stdio.log');
}

function isClosedPipeError(error: NodeJS.ErrnoException): boolean {
  return error.code === 'EPIPE' || error.code === 'ERR_STREAM_DESTROYED';
}

function handleOutputError(streamName: 'stdout' | 'stderr', error: NodeJS.ErrnoException): void {
  if (isClosedPipeError(error)) return;
  try {
    const logPath = atlasLogPath();
    mkdirSync(path.dirname(logPath), { recursive: true });
    appendFileSync(logPath, `${JSON.stringify({
      timestamp: new Date().toISOString(),
      event: 'main_process_output_error',
      stream: streamName,
      code: error.code,
      message: error.message,
    })}\n`);
  } catch {
    // The fallback logger must never turn an output stream error into a process crash.
  }
}

// This module is imported first by electron.ts, before application code can log.
process.stdout.on('error', (error: NodeJS.ErrnoException) => handleOutputError('stdout', error));
process.stderr.on('error', (error: NodeJS.ErrnoException) => handleOutputError('stderr', error));
