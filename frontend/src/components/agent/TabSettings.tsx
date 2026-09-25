'use client';

import { useState, useEffect } from 'react';
import { useAgentDetails, useUpdateAgentSettings } from '@/hooks/useAgent';
import { useModelReasoning } from '@/hooks/useModelReasoning';
import { useToast } from '@/components/ui/toast';
import { Button } from '@/components/ui/button';
import { Input, Textarea } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/card';
import { PresetPicker } from '@/components/agent/PresetPicker';
import {
  EMPTY_FIRST_COMMENT,
  FirstCommentSettingsSection,
  readFirstComment,
  type FirstCommentDraft,
} from '@/components/agent/FirstCommentSettings';
import { DEFAULT_MODEL, optionsIncluding } from '@/lib/models';
import { agentsApi } from '@/lib/api';
import { pickReasoningValue, reasoningLabel, reasoningOptionValues } from '@/lib/reasoning';
import { agentSettingsSchema, type AgentSettingsValues } from '@/lib/validators';
import type { ApiError } from '@/types';

// В форме у вариантов первого комментария есть ключи строк; при разборе схемой
// они отбрасываются и в настройки не попадают.
type SettingsFormValues = Omit<AgentSettingsValues, 'first_comment'> & {
  first_comment: FirstCommentDraft;
};
type TextField = Exclude<keyof AgentSettingsValues, 'first_comment'>;

export function TabSettings({ agentId }: { agentId: string }) {
  const { toast } = useToast();
  const { data: details, isLoading } = useAgentDetails(agentId);
  const update = useUpdateAgentSettings(agentId);
  const { data: reasoningByModel } = useModelReasoning();

  const [values, setValues] = useState<SettingsFormValues>({
    name: '', soul_prompt: '', reasoning_effort: 'high', model: DEFAULT_MODEL,
    first_comment: EMPTY_FIRST_COMMENT,
  });
  const [formErrors, setFormErrors] = useState<Partial<Record<keyof AgentSettingsValues, string>>>({});
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (details) {
      setValues({
        name: details.name,
        soul_prompt: details.soul_prompt ?? '',
        reasoning_effort:
          (details.settings?.reasoning_effort as AgentSettingsValues['reasoning_effort']) ?? 'high',
        model: (details.settings?.model as string) ?? DEFAULT_MODEL,
        first_comment: readFirstComment(details.settings),
      });
    }
  }, [details]);

  const reasoningMeta = reasoningByModel?.[values.model];
  const reasoningOptions = reasoningOptionValues(reasoningMeta);

  useEffect(() => {
    const current = values.reasoning_effort ?? '';
    const picked = pickReasoningValue(current, reasoningOptions, reasoningMeta);
    if (picked !== undefined && picked !== current) {
      setValues((v) => ({ ...v, reasoning_effort: picked as AgentSettingsValues['reasoning_effort'] }));
    }
  }, [values.model, values.reasoning_effort, reasoningOptions, reasoningMeta]);

  const set = (field: TextField, value: string) => {
    setValues((v) => ({ ...v, [field]: value }));
    setDirty(true);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    const result = agentSettingsSchema.safeParse(values);
    if (!result.success) {
      const fe: Partial<Record<keyof AgentSettingsValues, string>> = {};
      result.error.issues.forEach(i => { fe[i.path[0] as keyof AgentSettingsValues] = i.message; });
      setFormErrors(fe);
      return;
    }
    setFormErrors({});
    try {
      // Merge instead of overwrite: keep settings keys the form does not own.
      const existingSettings = (details?.settings ?? {}) as Record<string, unknown>;
      const submissionData = {
        name: result.data.name,
        soul_prompt: result.data.soul_prompt,
        settings: {
          ...existingSettings,
          // Models without exposed effort selection must not receive a stale
          // stored effort: "none" keeps the request clean.
          reasoning_effort: reasoningOptions === null ? 'none' : result.data.reasoning_effort,
          model: result.data.model,
          first_comment: result.data.first_comment ?? EMPTY_FIRST_COMMENT,
        },
      };
      await update.mutateAsync(submissionData);
      // The runtime is built once: new settings need a rebuild.
      await agentsApi.reload(agentId);
      toast('Настройки сохранены', 'success');
      setDirty(false);
    } catch (e: unknown) {
      toast((e as ApiError).message ?? 'Ошибка сохранения', 'error');
    }
  };

  if (isLoading) return <SettingsSkeleton />;

  return (
    <form onSubmit={handleSave} className="max-w-2xl space-y-6">
      <Input
        label="Имя агента"
        value={values.name}
        onChange={(e) => set('name', e.target.value)}
        error={formErrors.name}
      />

      <div className="space-y-2">
        <div className="flex justify-end">
          <PresetPicker
            currentValue={values.soul_prompt}
            onApply={(body) => set('soul_prompt', body)}
          />
        </div>
        <Textarea
          label="SOUL.md — Характер"
          value={values.soul_prompt}
          onChange={(e) => set('soul_prompt', e.target.value)}
          error={formErrors.soul_prompt}
          className="min-h-[200px]"
          showCount
          maxLength={50000}
          hint="Описание личности, стиля общения и особенностей агента"
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-mono font-medium text-void-300 uppercase tracking-wider">
          Модель
        </label>
        <select
          value={values.model}
          onChange={(e) => set('model', e.target.value)}
          className="flex h-10 w-full rounded-sm bg-void-800 border border-void-600 px-3 py-2 font-mono text-base sm:text-sm text-void-100 placeholder:text-void-500 transition-colors duration-150 focus:outline-none focus:ring-1 focus:ring-plasma-500 focus:border-plasma-600 hover:border-void-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {optionsIncluding(values.model).map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
        {formErrors.model && (
          <p className="text-xs text-crimson-400 font-mono flex items-center gap-1">
            <span aria-hidden="true">✗</span>
            {formErrors.model}
          </p>
        )}
      </div>

      {reasoningOptions !== null && (
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-mono font-medium text-void-300 uppercase tracking-wider">
            Уровень рассуждения (Reasoning Effort)
          </label>
          <select
            value={values.reasoning_effort ?? ''}
            onChange={(e) => set('reasoning_effort', e.target.value)}
            className="flex h-10 w-full rounded-sm bg-void-800 border border-void-600 px-3 py-2 font-mono text-base sm:text-sm text-void-100 placeholder:text-void-500 transition-colors duration-150 focus:outline-none focus:ring-1 focus:ring-plasma-500 focus:border-plasma-600 hover:border-void-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {reasoningOptions.map((effort) => (
              <option key={effort} value={effort}>
                {reasoningLabel(effort)}
              </option>
            ))}
          </select>
          {formErrors.reasoning_effort && (
            <p className="text-xs text-crimson-400 font-mono flex items-center gap-1">
              <span aria-hidden="true">✗</span>
              {formErrors.reasoning_effort}
            </p>
          )}
        </div>
      )}

      <FirstCommentSettingsSection
        agentId={agentId}
        value={values.first_comment}
        onChange={(update) => {
          setValues((v) => ({ ...v, first_comment: update(v.first_comment) }));
          setDirty(true);
        }}
        error={formErrors.first_comment}
      />

      <div className="flex items-center gap-3 pt-2">
        <Button type="submit" isLoading={update.isPending} disabled={!dirty}>
          Сохранить изменения
        </Button>
        {dirty && (
          <span className="font-mono text-xs text-amber-400">● Есть несохранённые изменения</span>
        )}
      </div>
    </form>
  );
}

export function SettingsSkeleton() {
  return (
    <div className="max-w-2xl space-y-6">
      {[120, 240, 200].map((h, i) => <Skeleton key={i} style={{ height: h }} />)}
    </div>
  );
}
