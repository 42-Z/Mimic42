'use client';

import { useResetContext } from '@/hooks/useAgents';
import { useToast } from '@/components/ui/toast';
import { ConfirmDialog } from '@/components/ui/modal';
import { sanitizeText } from '@/lib/sanitize';
import type { ApiError } from '@/types';

interface ResetContextDialogProps {
  agentId: string;
  agentName?: string;
  isOpen: boolean;
  onClose: () => void;
}

/**
 * Confirmation for resetting an agent's short-term context. Shared by the
 * dashboard card and the agent's Actions tab.
 */
export function ResetContextDialog({ agentId, agentName, isOpen, onClose }: ResetContextDialogProps) {
  const { toast } = useToast();
  const resetContext = useResetContext(agentId);
  const subject = agentName ? `Агент «${sanitizeText(agentName)}»` : 'Агент';

  return (
    <ConfirmDialog
      isOpen={isOpen}
      onClose={onClose}
      onConfirm={() => {
        resetContext.mutate(undefined, {
          onSuccess: () => {
            onClose();
            toast('Контекст сброшен', 'success');
          },
          onError: (e: unknown) => toast((e as ApiError).message, 'error'),
        });
      }}
      title="Сбросить контекст?"
      description={`${subject} перестанет учитывать недавние сообщения во всех чатах и ответит на следующее так, будто разговор начинается заново. История на дашборде и долгосрочная память останутся.`}
      confirmLabel="Сбросить"
      variant="danger"
      isLoading={resetContext.isPending}
    />
  );
}
