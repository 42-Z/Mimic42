'use client';

import { useCallback, useEffect, useState } from 'react';
import { File, ImageOff, ChevronLeft, ChevronRight } from 'lucide-react';
import { useMediaUrl } from '@/hooks/useMediaUrl';
import { Badge } from '@/components/ui/badge';
import { Modal } from '@/components/ui/modal';
import { cn } from '@/lib/utils';
import type { MediaItem } from '@/types';

function mediaMime(item: MediaItem): string {
  return item.mime_type.split(';')[0]?.trim().toLowerCase() ?? '';
}

function isImageMedia(item: MediaItem): boolean {
  return item.kind === 'photo' || (item.kind === 'sticker' && mediaMime(item) === 'image/webp');
}

function isVideoSticker(item: MediaItem): boolean {
  return item.kind === 'sticker' && mediaMime(item) === 'video/webm';
}

function MediaFallback({
  item,
  reason,
  error = false,
}: {
  item: MediaItem;
  reason: string;
  error?: boolean;
}) {
  return (
    <Badge variant={error ? 'destructive' : 'outline'}>
      <ImageOff aria-hidden="true" />
      <span className="min-w-0 break-all">{item.name} ({reason})</span>
    </Badge>
  );
}

function MediaView({
  agentId,
  item,
  compact = false,
}: {
  agentId: string;
  item: MediaItem;
  compact?: boolean;
}) {
  // TGS и испорченные записи браузер не покажет: вместо бессмысленной загрузки
  // ради битой иконки — чип с именем. Хук всё равно вызывается безусловно,
  // поэтому путь для них глушится через null.
  const unsupportedSticker = item.kind === 'sticker' && !isImageMedia(item) && !isVideoSticker(item);
  const { url, status } = useMediaUrl(agentId, unsupportedSticker ? null : item.storage_path);
  const [failedUrl, setFailedUrl] = useState<string | null>(null);

  if (!item.storage_path) {
    return <MediaFallback item={item} reason="файл не сохранён" />;
  }
  if (unsupportedSticker) {
    return (
      <MediaFallback
        item={item}
        reason={
          mediaMime(item) === 'application/x-tgsticker' ? 'анимированный стикер' : 'предпросмотр недоступен'
        }
      />
    );
  }
  if (status === 'error' || (url !== null && failedUrl === url)) {
    return <MediaFallback item={item} reason="недоступно" error />;
  }
  if (!url) {
    return <span className="font-mono text-[10px] text-muted-foreground">Загрузка медиа…</span>;
  }

  if (isImageMedia(item)) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={url}
        alt={item.name}
        loading="lazy"
        decoding="async"
        onError={() => setFailedUrl(url)}
        className={cn(
          'rounded-sm border border-border',
          compact ? 'size-16 flex-none' : 'max-h-40 max-w-56',
          item.kind === 'sticker' ? 'object-contain' : 'object-cover',
        )}
      />
    );
  }
  if (isVideoSticker(item)) {
    return (
      <video
        src={url}
        aria-label={`Стикер ${item.name}`}
        controls
        loop
        muted
        playsInline
        onError={() => setFailedUrl(url)}
        className="max-h-40 max-w-56 rounded-sm border border-border object-contain"
      />
    );
  }
  if (item.kind === 'voice') {
    return <audio controls src={url} className="h-9 max-w-full" />;
  }
  if (item.kind === 'round') {
    return <video controls src={url} className="max-w-40 rounded-sm border border-border" />;
  }
  return (
    <a
      href={url}
      download={item.name}
      className="inline-flex items-center gap-1.5 rounded-sm border border-border px-2 py-1 font-mono text-[10px] text-plasma-400 transition-colors hover:text-plasma-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      <File className="h-3 w-3" />
      {item.name} · {Math.max(1, Math.round(item.size / 1024))} КБ
    </a>
  );
}

function LightboxImage({ agentId, item }: { agentId: string; item: MediaItem }) {
  const { url, status } = useMediaUrl(agentId, item.storage_path);
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  if (!item.storage_path) {
    return <MediaFallback item={item} reason="файл не сохранён" />;
  }
  if (status === 'error' || (url !== null && failedUrl === url)) {
    return <MediaFallback item={item} reason="недоступно" error />;
  }
  if (!url) return null;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={url}
      alt={item.name}
      onError={() => setFailedUrl(url)}
      className="max-h-[70vh] w-auto mx-auto"
    />
  );
}

export function MediaContent({ agentId, items }: { agentId: string; items: MediaItem[] }) {
  // Индекс, а не объект: после пересборки items (realtime-инвалидация) ссылки
  // меняются, и поиск по идентичности ломает навигацию лайтбокса.
  const [previewIndex, setPreviewIndex] = useState<number | null>(null);

  const images = items?.filter(isImageMedia) ?? [];
  const preview = previewIndex !== null ? (images[previewIndex] ?? null) : null;

  // Стрелки листают галерею; порядок — как в ряду превью.
  const step = useCallback(
    (delta: number) => {
      setPreviewIndex((current) => {
        if (current === null || images.length < 2) return current;
        return (current + delta + images.length) % images.length;
      });
    },
    [images.length],
  );

  useEffect(() => {
    if (previewIndex === null) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'ArrowLeft') step(-1);
      if (event.key === 'ArrowRight') step(1);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [previewIndex, step]);

  if (!items?.length) return null;

  const others = items.filter((item) => !isImageMedia(item));
  const gallery = images.length > 1;

  return (
    <div className="flex flex-wrap items-center gap-2">
      {gallery ? (
        <div
          data-testid="media-gallery"
          className="flex flex-row items-center gap-1.5 overflow-x-auto"
        >
          {images.map((item, i) => (
            <button
              key={`${item.storage_path ?? i}-${item.name}`}
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                setPreviewIndex(i);
              }}
              className="cursor-zoom-in rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              <MediaView agentId={agentId} item={item} compact />
            </button>
          ))}
        </div>
      ) : (
        images.map((item, i) => (
          <button
            key={`${item.storage_path ?? i}-${item.name}`}
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              setPreviewIndex(i);
            }}
            className="cursor-zoom-in rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            <MediaView agentId={agentId} item={item} />
          </button>
        ))
      )}
      {others.map((item, i) => (
        <MediaView key={`${item.storage_path ?? i}-${item.name}`} agentId={agentId} item={item} />
      ))}
      <Modal
        isOpen={preview !== null}
        onClose={() => setPreviewIndex(null)}
        title={preview?.name ?? ''}
        size="lg"
      >
        {preview && (
          <div className="relative">
            <LightboxImage agentId={agentId} item={preview} />
            {images.length > 1 && (
              <>
                <button
                  type="button"
                  aria-label="Предыдущее изображение"
                  onClick={(event) => {
                    event.stopPropagation();
                    step(-1);
                  }}
                  className="absolute left-0 top-1/2 -translate-y-1/2 rounded-sm border border-border bg-card/80 p-2 text-muted-foreground backdrop-blur-sm transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                >
                  <ChevronLeft className="h-6 w-6" />
                </button>
                <button
                  type="button"
                  aria-label="Следующее изображение"
                  onClick={(event) => {
                    event.stopPropagation();
                    step(1);
                  }}
                  className="absolute right-0 top-1/2 -translate-y-1/2 rounded-sm border border-border bg-card/80 p-2 text-muted-foreground backdrop-blur-sm transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                >
                  <ChevronRight className="h-6 w-6" />
                </button>
              </>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
