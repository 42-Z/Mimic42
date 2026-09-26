'use client';

import { useTokenUsage } from '@/hooks/useTelegramSession';
import { Card, Skeleton } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { formatCompactNumber } from '@/lib/format';

export function TokenUsageCard({ agentId }: { agentId: string }) {
  const { data, isLoading, isError } = useTokenUsage(agentId);

  return (
    <Card variant="glass" padding="md" data-testid="token-usage-card">
      <h3 className="font-mono text-xs text-void-400 uppercase tracking-wider mb-4">
        Токены за всё время
      </h3>
      <TokenUsageStats
        inputTokens={data?.input_tokens ?? 0}
        outputTokens={data?.output_tokens ?? 0}
        isLoading={isLoading}
        isError={isError}
      />
    </Card>
  );
}

export function TokenUsageStats({
  inputTokens,
  outputTokens,
  isLoading,
  isError,
}: {
  inputTokens: number;
  outputTokens: number;
  isLoading: boolean;
  isError: boolean;
}) {
  if (isLoading) {
    return <Skeleton className="h-10 w-64" />;
  }

  if (isError) {
    return (
      <p className="font-mono text-xs text-crimson-400" role="alert">
        Не удалось загрузить счётчики
      </p>
    );
  }

  return (
    <div className="flex flex-wrap gap-x-10 gap-y-4">
      <TokenStat label="Входные" value={inputTokens} className="text-plasma-400" />
      <TokenStat label="Выходные" value={outputTokens} className="text-neon-400" />
      <TokenStat label="Всего" value={inputTokens + outputTokens} className="text-void-200" />
    </div>
  );
}

function TokenStat({
  label,
  value,
  className,
}: {
  label: string;
  value: number;
  className: string;
}) {
  return (
    <div title={value.toLocaleString('ru-RU')}>
      <div className={cn('font-mono text-2xl', className)}>{formatCompactNumber(value)}</div>
      <div className="font-mono text-[10px] uppercase tracking-wider text-void-300 mt-1">
        {label}
      </div>
    </div>
  );
}
