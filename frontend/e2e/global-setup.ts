import { spawnSync } from 'node:child_process';

/**
 * Занимает один из двух слотов тестовых аккаунтов на весь прогон e2e —
 * тестовая база одна на всех, поэтому параллельный локальный прогон и
 * прогон CI не должны наступать друг другу на пальцы.
 */
function runSlotCli(args: string[]): string {
  const result = spawnSync('uv', ['run', 'python', '-m', 'mimic42.testing.slot_cli', ...args], {
    cwd: '..',
    encoding: 'utf8',
  });
  if (result.status !== 0) {
    throw new Error(`slot_cli ${args.join(' ')} упал: ${result.stderr}`);
  }
  return result.stdout.trim();
}

export default function globalSetup(): void {
  const slot = runSlotCli(['acquire']);
  process.env['E2E_SLOT'] = slot;
  // Описание слота (персоны + пароль) кладётся в окружение здесь, а не в
  // helpers.ts — чтобы каждый воркер не перезапускал uv run на импорте.
  process.env['E2E_SLOT_DESCRIPTION'] = runSlotCli(['describe', slot]);
}
