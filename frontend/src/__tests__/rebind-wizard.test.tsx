import { afterEach, describe, expect, mock, spyOn, test } from 'bun:test';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RebindWizard } from '@/components/agent/RebindPageClient';
import { agentsApi, onboardingApi } from '@/lib/api';

const AGENT_ID = '11111111-1111-4111-8111-111111111111';
const ONBOARDING_ID = '22222222-2222-4222-8222-222222222222';

function renderWizard() {
  const onNavigate = mock((_href: string) => {});
  const onInvalidate = mock(() => {});
  const onToast = mock((_message: string, _variant: 'success' | 'error') => {});
  render(
    <RebindWizard
      agentId={AGENT_ID}
      knownPhone="+79991234567"
      onNavigate={onNavigate}
      onInvalidate={onInvalidate}
      onToast={onToast}
    />,
  );
  return { onNavigate, onInvalidate, onToast };
}

afterEach(() => {
  mock.restore();
});

describe('RebindWizard', () => {
  test('requests a code, verifies it, confirms the rebind and invalidates agent data', async () => {
    const rebind = spyOn(agentsApi, 'rebindTelegram').mockResolvedValue({
      onboarding_id: ONBOARDING_ID,
      owner_id: AGENT_ID,
      authorization_status: 'code_requested',
      phone_number: '+79991234567',
    });
    const submitCode = spyOn(onboardingApi, 'submitCode').mockResolvedValue({
      onboarding_id: ONBOARDING_ID,
      owner_id: AGENT_ID,
      authorization_status: 'authorized',
      phone_number: '+79991234567',
    });
    const confirm = spyOn(agentsApi, 'confirmRebind').mockResolvedValue({
      agent_id: AGENT_ID,
      owner_id: AGENT_ID,
      state: 'stopped',
    });
    const user = userEvent.setup();
    const { onInvalidate } = renderWizard();

    expect((await screen.findByText(/Код придёт в Telegram/)).textContent).toContain(
      '+799******67',
    );
    await user.type(screen.getByLabelText('Код подтверждения'), '12345');
    await user.click(screen.getByRole('button', { name: 'Подтвердить →' }));

    expect(await screen.findByText('Telegram перепривязан')).toBeTruthy();
    expect(rebind).toHaveBeenCalledWith(AGENT_ID);
    expect(submitCode).toHaveBeenCalledWith(ONBOARDING_ID, { code: '12345' });
    expect(confirm).toHaveBeenCalledWith(AGENT_ID, { onboarding_id: ONBOARDING_ID });
    expect(onInvalidate).toHaveBeenCalledTimes(1);
  });

  test('retries only the idempotent confirmation after a lifecycle failure', async () => {
    spyOn(agentsApi, 'rebindTelegram').mockResolvedValue({
      onboarding_id: ONBOARDING_ID,
      owner_id: AGENT_ID,
      authorization_status: 'code_requested',
      phone_number: '+79991234567',
    });
    const submitCode = spyOn(onboardingApi, 'submitCode').mockResolvedValue({
      onboarding_id: ONBOARDING_ID,
      owner_id: AGENT_ID,
      authorization_status: 'authorized',
      phone_number: '+79991234567',
    });
    const confirm = spyOn(agentsApi, 'confirmRebind')
      .mockRejectedValueOnce({ message: 'Не удалось пересобрать агента' })
      .mockResolvedValueOnce({ agent_id: AGENT_ID, owner_id: AGENT_ID, state: 'stopped' });
    const user = userEvent.setup();
    renderWizard();

    await screen.findByLabelText('Код подтверждения');
    await user.type(screen.getByLabelText('Код подтверждения'), '12345');
    await user.click(screen.getByRole('button', { name: 'Подтвердить →' }));
    expect(await screen.findByText(/Telegram уже привязан/)).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'Повторить' }));
    await waitFor(() => expect(screen.getByText('Telegram перепривязан')).toBeTruthy());
    expect(submitCode).toHaveBeenCalledTimes(1);
    expect(confirm).toHaveBeenCalledTimes(2);
  });
});
