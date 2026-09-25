import { describe, expect, test } from 'bun:test';
import { render, screen } from '@testing-library/react';
import { AgentIdentity } from '@/components/agents/AgentIdentity';

describe('AgentIdentity', () => {
  test('показывает @юзернейм рядом с прозвищем бота', () => {
    render(<AgentIdentity name="Мой агент" username="mimic42" subtitle="+7 999 123-45-67" />);
    expect(screen.getByText('Мой агент')).toBeTruthy();
    expect(screen.getByText('@mimic42')).toBeTruthy();
  });

  test('@ добавляется компонентом, а не данными', () => {
    render(<AgentIdentity name="Мой агент" username="@mimic42" />);
    expect(screen.getByText('@mimic42')).toBeTruthy();
    expect(screen.queryByText('@@mimic42')).toBeNull();
  });

  test('без юзернейма лишней надписи нет', () => {
    render(<AgentIdentity name="Мой агент" username={null} />);
    expect(screen.getByText('Мой агент')).toBeTruthy();
    expect(screen.queryByText(/^@/)).toBeNull();
  });

  test('пустой юзернейм не рисует «@»', () => {
    render(<AgentIdentity name="Мой агент" username="   " />);
    expect(screen.queryByText(/^@/)).toBeNull();
  });

  test('подпись под именем сохраняется', () => {
    render(<AgentIdentity name="Мой агент" username="mimic42" subtitle="Telegram не подключён" />);
    expect(screen.getByText('Telegram не подключён')).toBeTruthy();
  });
});
