'use client';

import { useLayoutEffect, useRef, useState } from 'react';
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

interface PresetEditorDialogProps {
  isOpen: boolean;
  onClose: () => void;
  initial?: PresetEditorInitial | null;
  onSave: (draft: PresetDraft) => Promise<void>;
}

/**
 * Создание и правка своего пресета. Сохранение отдаётся странице через
 * `onSave` (внутри — `mutateAsync`), компонент только валидирует и ждёт.
 */
export function PresetEditorDialog({ isOpen, ...props }: PresetEditorDialogProps) {
  if (!isOpen) return null;

  return <PresetEditorForm key={props.initial?.id ?? 'new'} {...props} />;
}

function PresetEditorForm({
  onClose,
  initial,
  onSave,
}: Omit<PresetEditorDialogProps, 'isOpen'>) {
  const [title, setTitle] = useState(initial?.title ?? '');
  const [summary, setSummary] = useState(initial?.summary ?? '');
  const [body, setBody] = useState(initial?.body ?? '');
  const [settings, setSettings] = useState<Record<string, unknown> | null>(
    initial?.settings ?? null,
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const savingRef = useRef(false);
  const activeRef = useRef(true);

  useLayoutEffect(() => {
    activeRef.current = true;
    return () => {
      activeRef.current = false;
    };
  }, []);

  const enabledTools = readEnabledTools(settings);
  const canSave = title.trim().length > 0 && body.trim().length > 0;

  const handleClose = () => {
    if (!savingRef.current) onClose();
  };

  const handleSave = async () => {
    if (!canSave || savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    setError(null);
    try {
      await onSave({
        title: title.trim(),
        summary: summary.trim(),
        body: body,
        settings: settings,
      });
      if (activeRef.current) onClose();
    } catch (cause) {
      if (activeRef.current) {
        setError(cause instanceof Error ? cause.message : 'Не удалось сохранить пресет');
      }
    } finally {
      savingRef.current = false;
      if (activeRef.current) setSaving(false);
    }
  };

  return (
    <Modal
      isOpen
      onClose={handleClose}
      title={initial ? 'Правка пресета' : 'Новый пресет'}
      size="lg"
      className="max-h-[85vh] overflow-y-auto"
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
          <Button type="button" variant="ghost" size="sm" onClick={handleClose} disabled={saving}>
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
