import { afterEach, describe, expect, mock, spyOn, test } from 'bun:test';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ResetContextDialog } from '@/components/agent/ResetContextDialog';
import { ToastProvider } from '@/components/ui/toast';
import { agentsApi } from '@/lib/api';

const AGENT_ID = '2dbc9cfd-4860-4c43-8c95-653d5155de00';

function renderDialog() {
  const onClose = mock(() => {});
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <ResetContextDialog agentId={AGENT_ID} agentName="Мимик 1" isOpen onClose={onClose} />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { onClose };
}

describe('ResetContextDialog', () => {
  afterEach(() => mock.restore());

  test('называет агента и обещает сохранить историю', () => {
    renderDialog();
    expect(screen.getByText('Сбросить контекст?')).toBeTruthy();
    expect(screen.getByText(/Агент «Мимик 1» перестанет учитывать недавние сообщения/)).toBeTruthy();
    expect(screen.getByText(/История на дашборде и долгосрочная память останутся/)).toBeTruthy();
  });

  test('подтверждение сбрасывает контекст этого агента и закрывает окно', async () => {
    const reset = spyOn(agentsApi, 'resetContext').mockResolvedValue({
      context_reset_at: '2026-09-22T19:00:00Z',
    });
    const { onClose } = renderDialog();

    await userEvent.click(screen.getByRole('button', { name: 'Сбросить' }));

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(reset).toHaveBeenCalledWith(AGENT_ID);
    expect(screen.getByText('Контекст сброшен')).toBeTruthy();
  });

  test('ошибка показывается, а окно остаётся открытым', async () => {
    spyOn(agentsApi, 'resetContext').mockRejectedValue({ status: 404, message: 'Ресурс не найден.' });
    const { onClose } = renderDialog();

    await userEvent.click(screen.getByRole('button', { name: 'Сбросить' }));

    await waitFor(() => expect(screen.getByText('Ресурс не найден.')).toBeTruthy());
    expect(onClose).not.toHaveBeenCalled();
  });
});
