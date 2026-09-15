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
  const acquired = JSON.parse(runSlotCli(['acquire'])) as { slot: string; holder: string };
  try {
    process.env['E2E_SLOT'] = acquired.slot;
    // Holder нужен teardown'у: освобождать слот можно только от имени того,
    // кто его занял, иначе протухший воркер снимет чужой живой лиз.
    process.env['E2E_SLOT_HOLDER'] = acquired.holder;
    // Описание слота (персоны) кладётся в окружение здесь, а не в
    // helpers.ts — чтобы каждый воркер не перезапускал uv run на импорте.
    // Пароля в нём нет: он берётся из TEST_USER_PASSWORD.
    process.env['E2E_SLOT_DESCRIPTION'] = runSlotCli(['describe', acquired.slot]);
  } catch (error) {
    runSlotCli(['release', acquired.slot, acquired.holder]);
    throw error;
  }
}
