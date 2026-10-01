import { describe, expect, mock, test } from 'bun:test';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ToolsSettings } from '@/components/agent/ToolsSettings';
import { TOOL_INFO } from '@/lib/tools/toolInfo';

const MESSAGES_NAMES = TOOL_INFO.filter((tool) => tool.group === 'messages').map(
  (tool) => tool.name,
);
const OTHER_NAMES = TOOL_INFO.filter((tool) => tool.group !== 'messages').map(
  (tool) => tool.name,
);

describe('ToolsSettings', () => {
  test('свёрнутые группы показывают счётчики, раскрытие показывает инструменты', async () => {
    const user = userEvent.setup();
    render(<ToolsSettings value={null} onChange={() => {}} />);
    const section = screen.getByTestId('tools-settings');
    expect(within(section).getByText('Включено 91 из 91')).toBeTruthy();
    expect(within(section).queryByRole('switch', { name: 'Отправка сообщения' })).toBeNull();

    await user.click(within(section).getByTestId('tool-group-messages'));
    expect(within(section).getByRole('switch', { name: 'Отправка сообщения' })).toBeTruthy();
  });

  test('выключение инструмента отдаёт явный список без него', async () => {
    const user = userEvent.setup();
    const onChange = mock((_next: string[] | null) => {});
    render(<ToolsSettings value={null} onChange={onChange} />);
    const section = screen.getByTestId('tools-settings');
    await user.click(within(section).getByTestId('tool-group-messages'));
    await user.click(within(section).getByRole('switch', { name: 'Отправка сообщения' }));

    const [next] = onChange.mock.calls[0] as [string[]];
    expect(next).not.toContain('send_text_message');
    expect(next).toContain('view_image');
    expect(next.length).toBe(90);
  });

  test('поиск находит по названию и раскрывает группы', async () => {
    const user = userEvent.setup();
    render(<ToolsSettings value={null} onChange={() => {}} />);
    const section = screen.getByTestId('tools-settings');
    await user.type(within(section).getByLabelText('Поиск'), 'Удаление канала');

    expect(within(section).getByRole('switch', { name: 'Удаление канала' })).toBeTruthy();
    expect(within(section).queryByRole('switch', { name: 'Отправка сообщения' })).toBeNull();
  });

  test('«Включить все» сбрасывает режим в null', async () => {
    const user = userEvent.setup();
    const onChange = mock((_next: string[] | null) => {});
    render(<ToolsSettings value={['send_text_message']} onChange={onChange} />);

    await user.click(screen.getByRole('button', { name: 'Включить все' }));

    expect(onChange).toHaveBeenCalledWith(null);
  });

  test('неизвестные каталогу имена сохраняются при переключении', async () => {
    const user = userEvent.setup();
    const onChange = mock((_next: string[] | null) => {});
    render(<ToolsSettings value={['future_tool', 'send_text_message']} onChange={onChange} />);
    const section = screen.getByTestId('tools-settings');
    await user.click(within(section).getByTestId('tool-group-messages'));
    await user.click(within(section).getByRole('switch', { name: 'Отправка сообщения' }));

    const [next] = onChange.mock.calls[0] as [string[]];
    expect(next).toContain('future_tool');
    expect(next).not.toContain('send_text_message');
  });

  test('пустой allowlist: счётчик нулевой, группа включает ровно свои 12', async () => {
    const user = userEvent.setup();
    const onChange = mock((_next: string[] | null) => {});
    render(<ToolsSettings value={[]} onChange={onChange} />);
    const section = screen.getByTestId('tools-settings');
    expect(within(section).getByText('Включено 0 из 91')).toBeTruthy();

    await user.click(
      within(section).getByRole('switch', { name: 'Все инструменты группы «Сообщения»' }),
    );

    const [next] = onChange.mock.calls[0] as [string[]];
    expect(next.length).toBe(12);
    expect(next).toEqual(MESSAGES_NAMES);
    expect(next).toContain('send_text_message');
  });

  test('режим «включены все»: выключение группы отдаёт явный список из 79 имён', async () => {
    const user = userEvent.setup();
    const onChange = mock((_next: string[] | null) => {});
    render(<ToolsSettings value={null} onChange={onChange} />);

    await user.click(
      screen.getByRole('switch', { name: 'Все инструменты группы «Сообщения»' }),
    );

    const [next] = onChange.mock.calls[0] as [string[]];
    expect(next.length).toBe(79);
    for (const name of MESSAGES_NAMES) expect(next).not.toContain(name);
    expect(next).toContain('view_image');
  });

  test('частично включённая группа: switch выключен, клик включает всю группу', async () => {
    const user = userEvent.setup();
    const onChange = mock((_next: string[] | null) => {});
    render(<ToolsSettings value={['send_text_message']} onChange={onChange} />);
    const groupSwitch = screen.getByRole('switch', {
      name: 'Все инструменты группы «Сообщения»',
    });
    expect(groupSwitch.getAttribute('aria-checked')).toBe('false');

    await user.click(groupSwitch);

    const [next] = onChange.mock.calls[0] as [string[]];
    expect(next.length).toBe(12);
    for (const name of MESSAGES_NAMES) expect(next).toContain(name);
    for (const name of OTHER_NAMES) expect(next).not.toContain(name);
  });
});
