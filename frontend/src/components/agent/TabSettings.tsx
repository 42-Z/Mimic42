'use client';

import { useState, useEffect } from 'react';
import { useAgentDetails, useUpdateAgentSettings } from '@/hooks/useAgent';
import { useModelReasoning } from '@/hooks/useModelReasoning';
import { useToast } from '@/components/ui/toast';
import { Button } from '@/components/ui/button';
import { Input, Textarea, Label } from '@/components/ui/input';
import { Skeleton, Badge } from '@/components/ui/card';
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
        <Label htmlFor="agent-model">Модель</Label>
        <select
          id="agent-model"
          value={values.model}
          onChange={(e) => set('model', e.target.value)}
          className="flex h-9 w-full rounded-sm border border-border bg-background px-3 py-1 font-mono text-sm text-foreground transition-colors hover:border-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background [&>option]:bg-card [&>option]:text-foreground"
        >
          {optionsIncluding(values.model).map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
        {formErrors.model && (
          <p role="alert" className="text-xs text-crimson-400 font-mono flex items-center gap-1">
            <span aria-hidden="true">✗</span>
            {formErrors.model}
          </p>
        )}
      </div>

      {reasoningOptions !== null && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="agent-reasoning">Уровень рассуждения</Label>
          <select
            id="agent-reasoning"
            value={values.reasoning_effort ?? ''}
            onChange={(e) => set('reasoning_effort', e.target.value)}
            className="flex h-9 w-full rounded-sm border border-border bg-background px-3 py-1 font-mono text-sm text-foreground transition-colors hover:border-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background [&>option]:bg-card [&>option]:text-foreground"
          >
            {reasoningOptions.map((effort) => (
              <option key={effort} value={effort}>
                {reasoningLabel(effort)}
              </option>
            ))}
          </select>
          {formErrors.reasoning_effort && (
            <p role="alert" className="text-xs text-crimson-400 font-mono flex items-center gap-1">
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
        {dirty && <Badge variant="amber">Есть несохранённые изменения</Badge>}
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
