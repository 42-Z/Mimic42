'use client';

import { useEffect, useState } from 'react';
import { Modal } from '@/components/ui/modal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ToolsSettings } from '@/components/agent/ToolsSettings';
import { readEnabledTools, mergeEnabledTools } from '@/lib/tools/agentTools';
import type { PresetDraft } from '@/hooks/usePresetMutations';

/** Существующий пресет для редактирования. */
export interface PresetEditorInitial {
  id: string;
  title: string;
  summary: string;
  body: string;
  settings: Record<string, unknown> | null;
}

/**
 * Создание и правка своего пресета. Сохранение отдаётся странице через
 * `onSave` (внутри — `mutateAsync`), компонент только валидирует и ждёт.
 */
export function PresetEditorDialog({
  isOpen,
  onClose,
  initial,
  onSave,
}: {
  isOpen: boolean;
  onClose: () => void;
  initial?: PresetEditorInitial | null;
  onSave: (draft: PresetDraft) => Promise<void>;
}) {
  const [title, setTitle] = useState('');
  const [summary, setSummary] = useState('');
  const [body, setBody] = useState('');
  const [settings, setSettings] = useState<Record<string, unknown> | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      setTitle(initial?.title ?? '');
      setSummary(initial?.summary ?? '');
      setBody(initial?.body ?? '');
      setSettings(initial?.settings ?? null);
      setError(null);
      setSaving(false);
    }
  }, [isOpen, initial]);

  const enabledTools = readEnabledTools(settings);
  const canSave = title.trim().length > 0 && body.trim().length > 0;

  const handleSave = async () => {
    if (!canSave || saving) return;
    setSaving(true);
    setError(null);
    try {
      await onSave({
        title: title.trim(),
        summary: summary.trim(),
        body: body,
        settings: settings,
      });
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось сохранить пресет');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={initial ? 'Правка пресета' : 'Новый пресет'}
      size="lg"
    >
      <form
        className="space-y-4"
        data-testid="preset-editor"
        onSubmit={(event) => {
          event.preventDefault();
          void handleSave();
        }}
      >
        <div className="space-y-1">
          <label htmlFor="preset-editor-title" className="font-mono text-xs text-muted-foreground">
            Название
          </label>
          <Input
            id="preset-editor-title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Как назовёшь характер"
          />
        </div>
        <div className="space-y-1">
          <label htmlFor="preset-editor-summary" className="font-mono text-xs text-muted-foreground">
            Короткое описание
          </label>
          <Input
            id="preset-editor-summary"
            value={summary}
            onChange={(event) => setSummary(event.target.value)}
            placeholder="Одной строкой — что делает Мимик"
          />
        </div>
        <div className="space-y-1">
          <label htmlFor="preset-editor-body" className="font-mono text-xs text-muted-foreground">
            Промпт
          </label>
          <textarea
            id="preset-editor-body"
            value={body}
            onChange={(event) => setBody(event.target.value)}
            rows={8}
            placeholder="Характер для SOUL.md — как в настройках мимика"
            className="w-full rounded-sm border border-border bg-background/60 p-3 font-mono text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </div>
        <div className="space-y-1">
          <p className="font-mono text-xs text-muted-foreground">Настройки инструментов</p>
          <ToolsSettings
            value={enabledTools}
            onChange={(next) => setSettings(mergeEnabledTools(settings ?? {}, next))}
          />
        </div>

        {error && (
          <p
            role="alert"
            data-testid="preset-editor-error"
            className="font-mono text-xs text-crimson-400"
          >
            {error}
          </p>
        )}

        <div className="flex items-center justify-end gap-3">
          <Button type="button" variant="ghost" size="sm" onClick={onClose}>
            Отмена
          </Button>
          <Button
            type="submit"
            size="sm"
            disabled={!canSave || saving}
            data-testid="preset-editor-save"
          >
            {saving ? 'Сохраняю…' : initial ? 'Сохранить' : 'Создать'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
