import { describe, expect, test } from 'bun:test';
import { render, screen } from '@testing-library/react';
import { TokenUsageStats } from '@/components/agent/TokenUsageCard';

describe('TokenUsageStats', () => {
  test('показывает входные, выходные и сумму', () => {
    render(<TokenUsageStats inputTokens={12_300} outputTokens={4_500} isLoading={false} />);
    expect(screen.getByText('12,3 тыс')).toBeTruthy();
    expect(screen.getByText('4,5 тыс')).toBeTruthy();
    expect(screen.getByText('16,8 тыс')).toBeTruthy();
    expect(screen.getByText('Входные')).toBeTruthy();
    expect(screen.getByText('Выходные')).toBeTruthy();
    expect(screen.getByText('Всего')).toBeTruthy();
  });

  test('нули показываются как нули', () => {
    render(<TokenUsageStats inputTokens={0} outputTokens={0} isLoading={false} />);
    expect(screen.getAllByText('0')).toHaveLength(3);
  });

  test('пока идёт загрузка — вместо чисел скелетон', () => {
    render(<TokenUsageStats inputTokens={0} outputTokens={0} isLoading />);
    expect(screen.queryByText('Всего')).toBeNull();
  });
});
