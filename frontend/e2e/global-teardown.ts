import { spawnSync } from 'node:child_process';

/**
 * Освобождает слот, занятый в global-setup.ts.
 *
 * Данные Dev-базы здесь намеренно НЕ чистятся: чистка идёт в начале
 * следующего прогона (auth.setup.ts дергает /__test__/reset), чтобы после
 * падения состояние можно было посмотреть глазами. Упавший прогон поэтому
 * оставляет агентов и черновики до следующего старта — это осознанный
 * размен, а не забытая уборка.
 */
export default function globalTeardown(): void {
  const slot = process.env['E2E_SLOT'];
  const holder = process.env['E2E_SLOT_HOLDER'];
  if (!slot || !holder) return;
  spawnSync(
    'uv',
    ['run', 'python', '-m', 'mimic42.testing.slot_cli', 'release', slot, holder],
    { cwd: '..', encoding: 'utf8' },
  );
}
