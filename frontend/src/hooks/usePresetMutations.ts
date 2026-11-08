'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { getSupabaseClient, type SupabaseBrowserClient } from '@/lib/supabase/client';
import { useAccount, useAccountQueryKeys } from '@/hooks/useAccount';
import type { Json } from '@/types/supabase';

/** Черновик пресета: название, описание, промпт и патч настроек. */
export interface PresetDraft {
  title: string;
  summary: string;
  body: string;
  settings: Record<string, unknown> | null;
}

export async function createPreset(client: SupabaseBrowserClient, draft: PresetDraft, signal?: AbortSignal) {
  signal?.throwIfAborted();
  // Слаг и owner_id проставляет серверный триггер, колонки клиенту не выданы;
  // но сгенерированный insert-тип требует slug. Отправляем только выданные
  // поля, строгость снимаем кастом на границе — так же, как Json в
  // useUpdateAgentSettings.
  const payload = {
    title: draft.title,
    summary: draft.summary,
    body: draft.body,
    settings: draft.settings as Json,
  };
  const request = client
    .from('prompt_presets')
    .insert(payload as never);
  const { error } = await (signal ? request.abortSignal(signal) : request);
  if (error) throw new Error(error.message);
}

export async function updatePreset(
  client: SupabaseBrowserClient,
  id: string,
  draft: PresetDraft,
  signal?: AbortSignal,
) {
  signal?.throwIfAborted();
  const request = client
    .from('prompt_presets')
    .update({
      title: draft.title,
      summary: draft.summary,
      body: draft.body,
      settings: draft.settings as Json,
    })
    .eq('id', id);
  const { error } = await (signal ? request.abortSignal(signal) : request);
  if (error) throw new Error(error.message);
}

export async function publishPreset(client: SupabaseBrowserClient, id: string, signal?: AbortSignal) {
  signal?.throwIfAborted();
  const request = client
    .from('prompt_presets')
    .update({ published_at: new Date().toISOString() })
    .eq('id', id);
  const { error } = await (signal ? request.abortSignal(signal) : request);
  if (error) throw new Error(error.message);
}

export async function unpublishPreset(client: SupabaseBrowserClient, id: string, signal?: AbortSignal) {
  signal?.throwIfAborted();
  const request = client
    .from('prompt_presets')
    .update({ published_at: null })
    .eq('id', id);
  const { error } = await (signal ? request.abortSignal(signal) : request);
  if (error) throw new Error(error.message);
}

export async function deletePreset(client: SupabaseBrowserClient, id: string, signal?: AbortSignal) {
  signal?.throwIfAborted();
  const request = client.from('prompt_presets').delete().eq('id', id);
  const { error } = await (signal ? request.abortSignal(signal) : request);
  if (error) throw new Error(error.message);
}

export async function favoritePreset(
  client: SupabaseBrowserClient,
  presetId: string,
  ownerId: string | null,
  signal?: AbortSignal,
) {
  signal?.throwIfAborted();
  if (!ownerId) throw new Error('Not authenticated');
  const request = client.from('preset_favorites').insert({
    owner_id: ownerId,
    preset_id: presetId,
  });
  const { error } = await (signal ? request.abortSignal(signal) : request);
  if (error) throw new Error(error.message);
}

export async function unfavoritePreset(client: SupabaseBrowserClient, favoriteId: string, signal?: AbortSignal) {
  signal?.throwIfAborted();
  const request = client
    .from('preset_favorites')
    .delete()
    .eq('id', favoriteId);
  const { error } = await (signal ? request.abortSignal(signal) : request);
  if (error) throw new Error(error.message);
}

export async function unfavoriteByPreset(client: SupabaseBrowserClient, presetId: string, signal?: AbortSignal) {
  signal?.throwIfAborted();
  const request = client
    .from('preset_favorites')
    .delete()
    .eq('preset_id', presetId);
  const { error } = await (signal ? request.abortSignal(signal) : request);
  if (error) throw new Error(error.message);
}

// Все мутации инвалидируют весь каталог: пресеты и избранное меняются вместе,
// а состав каталога зависит и от published_at.
function useInvalidatePresets() {
  const queryKeys = useAccountQueryKeys();
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: queryKeys.presets.all });
  };
}

export function useCreatePreset() {
  const account = useAccount();
  const invalidate = useInvalidatePresets();
  return useMutation({
    mutationFn: (draft: PresetDraft) => createPreset(getSupabaseClient(), draft, account?.controller.signal),
    onSettled: invalidate,
  });
}

export function useUpdatePreset() {
  const account = useAccount();
  const invalidate = useInvalidatePresets();
  return useMutation({
    mutationFn: ({ id, draft }: { id: string; draft: PresetDraft }) =>
      updatePreset(getSupabaseClient(), id, draft, account?.controller.signal),
    onSettled: invalidate,
  });
}

export function usePublishPreset() {
  const account = useAccount();
  const invalidate = useInvalidatePresets();
  return useMutation({
    mutationFn: (id: string) => publishPreset(getSupabaseClient(), id, account?.controller.signal),
    onSettled: invalidate,
  });
}

export function useUnpublishPreset() {
  const account = useAccount();
  const invalidate = useInvalidatePresets();
  return useMutation({
    mutationFn: (id: string) => unpublishPreset(getSupabaseClient(), id, account?.controller.signal),
    onSettled: invalidate,
  });
}

export function useDeletePreset() {
  const account = useAccount();
  const invalidate = useInvalidatePresets();
  return useMutation({
    mutationFn: (id: string) => deletePreset(getSupabaseClient(), id, account?.controller.signal),
    onSettled: invalidate,
  });
}

export function useFavoritePreset() {
  const account = useAccount();
  const invalidate = useInvalidatePresets();
  return useMutation({
    mutationFn: (presetId: string) => favoritePreset(
      getSupabaseClient(), presetId, account?.userId ?? null, account?.controller.signal,
    ),
    onSettled: invalidate,
  });
}

export function useUnfavoritePreset() {
  const account = useAccount();
  const invalidate = useInvalidatePresets();
  return useMutation({
    mutationFn: (favoriteId: string) => unfavoritePreset(getSupabaseClient(), favoriteId, account?.controller.signal),
    onSettled: invalidate,
  });
}

export function useUnfavoriteByPreset() {
  const account = useAccount();
  const invalidate = useInvalidatePresets();
  return useMutation({
    mutationFn: (presetId: string) => unfavoriteByPreset(getSupabaseClient(), presetId, account?.controller.signal),
    onSettled: invalidate,
  });
}
