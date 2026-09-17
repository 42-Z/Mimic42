'use client';

import { useCallback, useEffect, useState } from 'react';
import { File, ImageOff, ChevronLeft, ChevronRight } from 'lucide-react';
import { useMediaUrl } from '@/hooks/useMediaUrl';
import { Modal } from '@/components/ui/modal';
import type { MediaItem } from '@/types';

const IMAGE_KINDS = new Set(['photo', 'sticker']);

function MediaView({
  agentId,
  item,
  compact = false,
}: {
  agentId: string;
  item: MediaItem;
  compact?: boolean;
}) {
  const { url, status } = useMediaUrl(agentId, item.storage_path);

  if (!item.storage_path) {
    return (
      <span className="inline-flex items-center gap-1.5 font-mono text-[10px] text-void-500 border border-void-700 rounded-sm px-2 py-1">
        <ImageOff className="h-3 w-3" />
        {item.name} (файл не сохранён)
      </span>
    );
  }
  if (status === 'error') {
    return (
      <span className="inline-flex items-center gap-1.5 font-mono text-[10px] text-crimson-400 border border-crimson-900 rounded-sm px-2 py-1">
        <ImageOff className="h-3 w-3" />
        {item.name} (недоступно)
      </span>
    );
  }
  if (!url) {
    return <span className="font-mono text-[10px] text-void-600">Загрузка медиа…</span>;
  }

  if (IMAGE_KINDS.has(item.kind)) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={url}
        alt={item.name}
        loading="lazy"
        decoding="async"
        className={
          compact
            ? 'h-16 w-16 flex-none rounded-sm border border-void-800 object-cover'
            : 'max-h-40 max-w-56 rounded-sm border border-void-800 object-cover'
        }
      />
    );
  }
  if (item.kind === 'voice') {
    return <audio controls src={url} className="h-9 max-w-full" />;
  }
  if (item.kind === 'round') {
    return <video controls src={url} className="max-w-40 rounded-sm border border-void-800" />;
  }
  return (
    <a
      href={url}
      download={item.name}
      className="inline-flex items-center gap-1.5 font-mono text-[10px] text-plasma-400 hover:text-plasma-300 border border-void-800 px-2 py-1 rounded-sm"
    >
      <File className="h-3 w-3" />
      {item.name} · {Math.max(1, Math.round(item.size / 1024))} КБ
    </a>
  );
}

function LightboxImage({ agentId, item }: { agentId: string; item: MediaItem }) {
  const { url } = useMediaUrl(agentId, item.storage_path);
  if (!url) return null;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={url} alt={item.name} className="max-h-[70vh] w-auto mx-auto" />
  );
}

export function MediaContent({ agentId, items }: { agentId: string; items: MediaItem[] }) {
  const [preview, setPreview] = useState<MediaItem | null>(null);

  const images = items?.filter((item) => IMAGE_KINDS.has(item.kind)) ?? [];

  // Стрелки листают галерею; порядок — как в ряду превью.
  const previewIndex = preview ? images.indexOf(preview) : -1;
  const step = useCallback(
    (delta: number) => {
      if (previewIndex < 0 || images.length < 2) return;
      setPreview(images[(previewIndex + delta + images.length) % images.length] ?? null);
    },
    [previewIndex, images],
  );

  useEffect(() => {
    if (!preview) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'ArrowLeft') step(1);
      if (event.key === 'ArrowRight') step(-1);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [preview, step]);

  if (!items?.length) return null;

  const others = items.filter((item) => !IMAGE_KINDS.has(item.kind));
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
                setPreview(item);
              }}
              className="cursor-zoom-in"
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
              setPreview(item);
            }}
            className="cursor-zoom-in"
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
        onClose={() => setPreview(null)}
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
                  className="absolute left-0 top-1/2 -translate-y-1/2 p-2 text-void-400 hover:text-void-100"
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
                  className="absolute right-0 top-1/2 -translate-y-1/2 p-2 text-void-400 hover:text-void-100"
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
