'use client';

import { Plus, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/input';

export function AttackTextList({
  texts,
  maxLength,
  errors,
  onChange,
  onAdd,
  onRemove,
}: {
  texts: string[];
  maxLength: number;
  errors: Record<string, string>;
  onChange: (index: number, value: string) => void;
  onAdd: () => void;
  onRemove: (index: number) => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      {texts.map((text, index) => (
        <div key={index} className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <Textarea
              label={`Текст ${index + 1}`}
              value={text}
              onChange={(event) => onChange(index, event.target.value)}
              error={errors[`texts.${index}`]}
              hint={
                index === 0
                  ? `До ${maxLength} символов. Отправляется как есть, без разметки.`
                  : undefined
              }
              showCount
              maxLength={maxLength}
              rows={3}
            />
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            onClick={() => onRemove(index)}
            disabled={texts.length === 1}
            aria-label={`Удалить текст ${index + 1}`}
            title={
              texts.length === 1
                ? 'В атаке должен остаться хотя бы один текст'
                : `Удалить текст ${index + 1}`
            }
            className="mt-6 text-muted-foreground hover:text-destructive"
          >
            <Trash2 className="size-4" aria-hidden="true" />
          </Button>
        </div>
      ))}
      {errors.texts && <p className="font-mono text-xs text-crimson-400">{errors.texts}</p>}
      <div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onAdd}
          leftIcon={<Plus className="size-3.5" aria-hidden="true" />}
        >
          Добавить текст
        </Button>
      </div>
    </div>
  );
}
