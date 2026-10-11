'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { getSupabaseClient, type SupabaseBrowserClient } from '@/lib/supabase/client';
import { queryKeys } from '@/lib/queryClient';
import type { Json } from '@/types/supabase';

/** Черновик пресета: название, описание, промпт и патч настроек. */
export interface PresetDraft {
  title: string;
  summary: string;
  body: string;
  settings: Record<string, unknown> | null;
}

export async function createPreset(client: SupabaseBrowserClient, draft: PresetDraft) {
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
  const { error } = await client
    .from('prompt_presets')
    .insert(payload as never);
  if (error) throw new Error(error.message);
}

export async function updatePreset(
  client: SupabaseBrowserClient,
  id: string,
  draft: PresetDraft,
) {
  const { error } = await client
    .from('prompt_presets')
    .update({
      title: draft.title,
      summary: draft.summary,
      body: draft.body,
      settings: draft.settings as Json,
    })
    .eq('id', id);
  if (error) throw new Error(error.message);
}export async function publishPreset(client: SupabaseBrowserClient, id: string) {
  const { error } = await client
    .from('prompt_presets')
    .update({ published_at: new Date().toISOString() })
    .eq('id', id);
  if (error) throw new Error(error.message);
}

export async function unpublishPreset(client: SupabaseBrowserClient, id: string) {
  const { error } = await client
    .from('prompt_presets')
    .update({ published_at: null })
    .eq('id', id);
  if (error) throw new Error(error.message);
}

export async function deletePreset(client: SupabaseBrowserClient, id: string) {
  const { error } = await client.from('prompt_presets').delete().eq('id', id);
  if (error) throw new Error(error.message);
}

export async function favoritePreset(client: SupabaseBrowserClient, presetId: string) {
  const { data: { user } } = await client.auth.getUser();
  if (!user) throw new Error('Not authenticated');
  const { error } = await client.from('preset_favorites').insert({
    owner_id: user.id,
    preset_id: presetId,
  });
  if (error) throw new Error(error.message);
}

export async function unfavoritePreset(client: SupabaseBrowserClient, favoriteId: string) {
  const { error } = await client
    .from('preset_favorites')
    .delete()
    .eq('id', favoriteId);
  if (error) throw new Error(error.message);
}

export async function unfavoriteByPreset(client: SupabaseBrowserClient, presetId: string) {
  const { error } = await client
    .from('preset_favorites')
    .delete()
    .eq('preset_id', presetId);
  if (error) throw new Error(error.message);
}

// Все мутации инвалидируют весь каталог: пресеты и избранное меняются вместе,
// а состав каталога зависит и от published_at.
function useInvalidatePresets() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: queryKeys.presets.all });
  };
}

export function useCreatePreset() {
  const invalidate = useInvalidatePresets();
  return useMutation({
    mutationFn: (draft: PresetDraft) => createPreset(getSupabaseClient(), draft),
    onSettled: invalidate,
  });
}

export function useUpdatePreset() {
  const invalidate = useInvalidatePresets();
  return useMutation({
    mutationFn: ({ id, draft }: { id: string; draft: PresetDraft }) =>
      updatePreset(getSupabaseClient(), id, draft),
    onSettled: invalidate,
  });
}

export function usePublishPreset() {
  const invalidate = useInvalidatePresets();
  return useMutation({
    mutationFn: (id: string) => publishPreset(getSupabaseClient(), id),
    onSettled: invalidate,
  });
}

export function useUnpublishPreset() {
  const invalidate = useInvalidatePresets();
  return useMutation({
    mutationFn: (id: string) => unpublishPreset(getSupabaseClient(), id),
    onSettled: invalidate,
  });
}

export function useDeletePreset() {
  const invalidate = useInvalidatePresets();
  return useMutation({
    mutationFn: (id: string) => deletePreset(getSupabaseClient(), id),
    onSettled: invalidate,
  });
}

export function useFavoritePreset() {
  const invalidate = useInvalidatePresets();
  return useMutation({
    mutationFn: (presetId: string) => favoritePreset(getSupabaseClient(), presetId),
    onSettled: invalidate,
  });
}

export function useUnfavoritePreset() {
  const invalidate = useInvalidatePresets();
  return useMutation({
    mutationFn: (favoriteId: string) => unfavoritePreset(getSupabaseClient(), favoriteId),
    onSettled: invalidate,
  });
}

export function useUnfavoriteByPreset() {
  const invalidate = useInvalidatePresets();
  return useMutation({
    mutationFn: (presetId: string) => unfavoriteByPreset(getSupabaseClient(), presetId),
    onSettled: invalidate,
  });
}
