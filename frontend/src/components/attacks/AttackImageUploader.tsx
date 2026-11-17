'use client';

import { useRef, useState } from 'react';
import { ImagePlus } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/card';
import { attacksApi } from '@/lib/api';
import { imageProblem } from '@/components/agent/FirstCommentSettings';
import { FIRST_COMMENT_MAX_IMAGE_BYTES } from '@/lib/validators';
import { AttackMediaThumb } from './AttackMediaStrip';
import type { ApiError, AttackImage } from '@/types';

const ACCEPTED_IMAGE_TYPES = ['image/jpeg', 'image/png'];
const MAX_IMAGE_MB = FIRST_COMMENT_MAX_IMAGE_BYTES / (1024 * 1024);
const INITIAL_VISIBLE = 12;
const LOAD_MORE = 24;
const MAX_UPLOAD_SIDE = 1280;
const MAX_UPLOAD_BYTES = 1_500_000;

async function prepareImage(file: File): Promise<File> {
  if (!file.type.startsWith('image/')) return file;
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, MAX_UPLOAD_SIDE / Math.max(bitmap.width, bitmap.height));
    if (scale === 1 && file.size <= MAX_UPLOAD_BYTES) {
      bitmap.close();
      return file;
    }
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const context = canvas.getContext('2d');
    if (!context) {
      bitmap.close();
      return file;
    }
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, 'image/jpeg', 0.84),
    );
    if (!blob) return file;
    const name = file.name.replace(/\.[^.]+$/, '') || 'image';
    return new File([blob], `${name}.jpg`, { type: 'image/jpeg' });
  } catch {
    return file;
  }
}

export function AttackImageUploader({
  images,
  onAdd,
  onRemove,
  error,
}: {
  images: AttackImage[];
  onAdd: (images: AttackImage[]) => void;
  onRemove: (path: string) => void;
  error?: string;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE);

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploadError(null);
    setUploading(true);

    const uploaded: AttackImage[] = [];
    let problem: string | null = null;

    try {
      for (const file of Array.from(files)) {
        const issue = imageProblem(file);
        if (issue) {
          problem ??= issue;
          continue;
        }
        try {
          const result = await attacksApi.uploadMedia(await prepareImage(file));
          uploaded.push({ path: result.storage_path, name: result.name });
        } catch (cause: unknown) {
          problem ??= (cause as ApiError).message ?? 'Не удалось загрузить картинку';
        }
      }
      if (uploaded.length > 0) onAdd(uploaded);
    } finally {
      setUploading(false);
      setUploadError(problem);
      if (fileInput.current) fileInput.current.value = '';
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <input
        ref={fileInput}
        type="file"
        accept={ACCEPTED_IMAGE_TYPES.join(',')}
        multiple
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        onChange={(event) => void handleFiles(event.target.files)}
      />

      {images.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {images.slice(Math.max(0, images.length - visibleCount)).map((image) => (
            <AttackMediaThumb
              key={image.path}
              media={image}
              size="lg"
              onRemove={(removed) => onRemove(removed.path)}
            />
          ))}
          {uploading && (
            <div className="flex size-24 items-center justify-center rounded-sm border border-dashed border-border bg-muted/40">
              <Spinner size="sm" />
            </div>
          )}
        </div>
      )}

      {images.length > visibleCount && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="w-fit"
          onClick={() => setVisibleCount((count) => count + LOAD_MORE)}
        >
          Показать ещё {Math.min(LOAD_MORE, images.length - visibleCount)}
        </Button>
      )}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Button
          type="button"
          variant="outline"
          size="sm"
          isLoading={uploading}
          onClick={() => fileInput.current?.click()}
          leftIcon={<ImagePlus className="size-3.5" aria-hidden="true" />}
        >
          {uploading ? 'Загружаем…' : 'Добавить картинки'}
        </Button>
        <span className="font-mono text-xs text-muted-foreground">
          JPEG или PNG до {MAX_IMAGE_MB} МБ. Больше 10 картинок — в каждый комментарий попадёт
          случайная десятка.
        </span>
      </div>

      {(uploadError || error) && (
        <p role="alert" className="flex items-center gap-1 font-mono text-xs text-crimson-400">
          <span aria-hidden="true">✗</span>
          {uploadError ?? error}
        </p>
      )}
    </div>
  );
}
