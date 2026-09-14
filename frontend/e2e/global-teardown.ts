import { spawnSync } from 'node:child_process';

/** Освобождает слот, занятый в global-setup.ts. */
export default function globalTeardown(): void {
  const slot = process.env['E2E_SLOT'];
  if (!slot) return;
  spawnSync('uv', ['run', 'python', '-m', 'mimic42.testing.slot_cli', 'release', slot], {
    cwd: '..',
    encoding: 'utf8',
  });
}
