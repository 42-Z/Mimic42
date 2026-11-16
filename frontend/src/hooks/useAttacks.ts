'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAccountApi } from '@/hooks/useAccountApi';
import { useAccountQueryKeys } from '@/hooks/useAccount';
import { STATUS_STALE_TIME } from '@/lib/queryClient';
import { attackIdSchema } from '@/lib/attacks/validators';
import type { AttackDraft, AttackPatch } from '@/types';

const LIST_POLL_MS = 5_000;
const DETAIL_POLL_MS = 3_000;

/**
 * Список атак: активные и архив. Опрос идёт только пока хоть одна атака идёт,
 * в покое список обновляют мутации.
 */
export function useAttacks() {
  const { attacks: attacksApi } = useAccountApi();
  const queryKeys = useAccountQueryKeys();

  return useQuery({
    queryKey: queryKeys.attacks.list(),
    queryFn: attacksApi.list,
    refetchInterval: (query) =>
      query.state.data?.active.some((attack) => attack.status === 'running')
        ? LIST_POLL_MS
        : false,
  });
}

/** Детали одной атаки; идущая кампания опрашивается чаще, чтобы прогресс жил. */
export function useAttack(id: string) {
  const { attacks: attacksApi } = useAccountApi();
  const queryKeys = useAccountQueryKeys();
  const isValidId = attackIdSchema.safeParse(id).success;

  return useQuery({
    queryKey: queryKeys.attacks.detail(id),
    queryFn: () => attacksApi.get(id),
    enabled: isValidId,
    refetchInterval: (query) =>
      query.state.data?.status === 'running' ? DETAIL_POLL_MS : false,
  });
}

/** Доступность мимиков для пикера: состояние, авторизация и активная атака. */
export function useAttackAgents() {
  const { attacks: attacksApi } = useAccountApi();
  const queryKeys = useAccountQueryKeys();

  return useQuery({
    queryKey: queryKeys.attacks.agents(),
    queryFn: attacksApi.agents,
    staleTime: STATUS_STALE_TIME,
  });
}

export function useCreateAttack() {
  const { attacks: attacksApi } = useAccountApi();
  const queryKeys = useAccountQueryKeys();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (body: AttackDraft) => attacksApi.create(body),
    onSuccess: (attack) => {
      qc.setQueryData(queryKeys.attacks.detail(attack.id), attack);
      qc.invalidateQueries({ queryKey: queryKeys.attacks.list() });
      qc.invalidateQueries({ queryKey: queryKeys.attacks.agents() });
    },
  });
}

/** Создание и немедленный запуск: кнопка «Создать и запустить» в форме. */
export function useCreateAndStartAttack() {
  const { attacks: attacksApi } = useAccountApi();
  const queryKeys = useAccountQueryKeys();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: async (body: AttackDraft) => {
      const attack = await attacksApi.create(body);
      return attacksApi.start(attack.id);
    },
    onSuccess: (attack) => {
      qc.setQueryData(queryKeys.attacks.detail(attack.id), attack);
      qc.invalidateQueries({ queryKey: queryKeys.attacks.list() });
      qc.invalidateQueries({ queryKey: queryKeys.attacks.agents() });
      qc.invalidateQueries({ queryKey: queryKeys.agents.all });
    },
  });
}

export function useUpdateAttack(id: string) {
  const { attacks: attacksApi } = useAccountApi();
  const queryKeys = useAccountQueryKeys();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (body: AttackPatch) => attacksApi.update(id, body),
    onSuccess: (attack) => {
      qc.setQueryData(queryKeys.attacks.detail(id), attack);
      qc.invalidateQueries({ queryKey: queryKeys.attacks.list() });
    },
  });
}

/**
 * Запуск атаки переводит назначенных мимиков в режим атаки, поэтому вместе с
 * атаками обновляется и `AgentStatus.attack_id`.
 */
export function useStartAttack(id: string) {
  const { attacks: attacksApi } = useAccountApi();
  const queryKeys = useAccountQueryKeys();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: () => attacksApi.start(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.attacks.detail(id) });
      qc.invalidateQueries({ queryKey: queryKeys.attacks.list() });
      qc.invalidateQueries({ queryKey: queryKeys.attacks.agents() });
      qc.invalidateQueries({ queryKey: queryKeys.agents.all });
    },
  });
}

export function useCancelAttack(id: string) {
  const { attacks: attacksApi } = useAccountApi();
  const queryKeys = useAccountQueryKeys();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: () => attacksApi.cancel(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.attacks.detail(id) });
      qc.invalidateQueries({ queryKey: queryKeys.attacks.list() });
      qc.invalidateQueries({ queryKey: queryKeys.attacks.agents() });
      qc.invalidateQueries({ queryKey: queryKeys.agents.all });
    },
  });
}

/** Повтор создаёт новый черновик; он сразу кладётся в кеш деталей. */
export function useRepeatAttack(id: string) {
  const { attacks: attacksApi } = useAccountApi();
  const queryKeys = useAccountQueryKeys();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: () => attacksApi.repeat(id),
    onSuccess: (attack) => {
      qc.setQueryData(queryKeys.attacks.detail(attack.id), attack);
      qc.invalidateQueries({ queryKey: queryKeys.attacks.list() });
      qc.invalidateQueries({ queryKey: queryKeys.attacks.agents() });
    },
  });
}

export function useAddAttackAgent(id: string) {
  const { attacks: attacksApi } = useAccountApi();
  const queryKeys = useAccountQueryKeys();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (agentId: string) => attacksApi.addAgent(id, agentId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.attacks.detail(id) });
      qc.invalidateQueries({ queryKey: queryKeys.attacks.list() });
      qc.invalidateQueries({ queryKey: queryKeys.attacks.agents() });
      qc.invalidateQueries({ queryKey: queryKeys.agents.all });
    },
  });
}

export function useRemoveAttackAgent(id: string) {
  const { attacks: attacksApi } = useAccountApi();
  const queryKeys = useAccountQueryKeys();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (agentId: string) => attacksApi.removeAgent(id, agentId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.attacks.detail(id) });
      qc.invalidateQueries({ queryKey: queryKeys.attacks.list() });
      qc.invalidateQueries({ queryKey: queryKeys.attacks.agents() });
      qc.invalidateQueries({ queryKey: queryKeys.agents.all });
    },
  });
}
