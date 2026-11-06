'use client';

import { useCallback, useEffect, useRef, useState, type SyntheticEvent } from 'react';
import { File, ImageOff, ChevronLeft, ChevronRight } from 'lucide-react';
import { useMediaLink } from '@/hooks/useMediaLink';
import { useMediaUrl } from '@/hooks/useMediaUrl';
import { Badge } from '@/components/ui/badge';
import { Modal } from '@/components/ui/modal';
import { cn } from '@/lib/utils';
import type { MediaItem } from '@/types';

type MediaShape = 'image' | 'video' | 'audio' | 'file';

function mediaMime(item: MediaItem): string {
  return item.mime_type.split(';')[0]?.trim().toLowerCase() ?? '';
}

function mediaShape(item: MediaItem): MediaShape {
  const mime = mediaMime(item);
  if (item.kind === 'photo') return 'image';
  if (item.kind === 'sticker') {
    if (mime === 'image/webp') return 'image';
    if (mime === 'video/webm') return 'video';
    return 'file';
  }
  if (item.kind === 'round') return 'video';
  if (item.kind === 'voice') return 'audio';
  if (mime.startsWith('video/')) return 'video';
  if (mime.startsWith('audio/')) return 'audio';
  return 'file';
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
  // ради битой иконки — чип с именем.
  const shape = mediaShape(item);
  const stream = shape === 'video' || shape === 'audio';
  const unsupportedSticker = item.kind === 'sticker' && shape === 'file';
  const blob = useMediaUrl(agentId, stream || unsupportedSticker ? null : item.storage_path);
  const { url, status } = blob;
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
  if (stream) {
    return (
      <StreamMedia
        key={`${agentId}:${item.storage_path}:${shape}`}
        agentId={agentId}
        item={item}
        shape={shape}
      />
    );
  }
  if (status === 'error' || (url !== null && failedUrl === url)) {
    return <MediaFallback item={item} reason="недоступно" error />;
  }
  if (!url) {
    return <span className="font-mono text-[10px] text-muted-foreground">Загрузка медиа…</span>;
  }

  if (shape === 'image') {
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

function StreamMedia({
  agentId,
  item,
  shape,
}: {
  agentId: string;
  item: MediaItem;
  shape: MediaShape;
}) {
  const { url, status, refresh } = useMediaLink(agentId, item.storage_path);
  const [failed, setFailed] = useState(false);
  const player = useRef<HTMLMediaElement | null>(null);
  const mounted = useRef(false);
  const terminal = useRef(false);
  const recoveryUsed = useRef(false);
  const recovering = useRef(false);
  const playIntent = useRef(false);
  const restore = useRef<{ time: number; resume: boolean } | null>(null);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const fail = () => {
    terminal.current = true;
    restore.current = null;
    setFailed(true);
  };

  const replaceSource = useCallback((
    media: HTMLMediaElement,
    nextUrl: string,
    resume: boolean,
    time = media.currentTime,
  ) => {
    restore.current = { time, resume };
    media.src = nextUrl;
    // Storage может вернуть ту же подпись в пределах одной секунды.
    media.load();
  }, []);

  const applyIdleSource = useCallback(() => {
    const media = player.current;
    if (!url || !media || terminal.current || recovering.current || restore.current) return;
    if ((!media.paused && !media.ended) || playIntent.current) return;
    if (media.getAttribute('src') !== url) replaceSource(media, url, false);
  }, [url, replaceSource]);

  useEffect(() => {
    const media = player.current;
    if (!url || !media || terminal.current) return;
    if (!media.getAttribute('src')) media.src = url;
    else applyIdleSource();
  }, [url, applyIdleSource]);

  const recover = async (event: SyntheticEvent<HTMLMediaElement>) => {
    const media = event.currentTarget;
    const code = media.error?.code;
    if (terminal.current || code === 1) return;
    if (code === 3) { fail(); return; }
    if (recovering.current) return;
    if (recoveryUsed.current) { fail(); return; }

    recoveryUsed.current = true;
    recovering.current = true;
    const resume = playIntent.current || !media.paused;
    const time = media.currentTime;
    const nextUrl = await refresh();
    if (!mounted.current || player.current !== media || terminal.current) return;
    recovering.current = false;
    if (!nextUrl) { fail(); return; }
    replaceSource(media, nextUrl, resume, time);
  };

  const onLoadedMetadata = (event: SyntheticEvent<HTMLMediaElement>) => {
    const media = event.currentTarget;
    const pending = restore.current;
    if (!pending || terminal.current) return;
    restore.current = null;
    if (Number.isFinite(pending.time) && pending.time > 0) {
      media.currentTime = Number.isFinite(media.duration)
        ? Math.min(pending.time, media.duration)
        : pending.time;
    }
    if (pending.resume) {
      // Отказ autoplay не означает, что подпись снова истекла.
      void media.play().catch(() => {
        if (mounted.current && player.current === media && media.paused) {
          playIntent.current = false;
        }
      });
    }
  };

  if (failed || status === 'error') {
    return <MediaFallback item={item} reason="недоступно" error />;
  }
  if (!url) {
    return <span className="font-mono text-[10px] text-muted-foreground">Загрузка медиа…</span>;
  }

  const events = {
    controls: true,
    onError: recover,
    onLoadedMetadata,
    onPlay: () => { playIntent.current = true; },
    onPlaying: () => {
      playIntent.current = true;
      if (!recovering.current && !restore.current) recoveryUsed.current = false;
    },
    onPause: (event: SyntheticEvent<HTMLMediaElement>) => {
      if (recovering.current || restore.current || event.currentTarget.error) return;
      playIntent.current = false;
      applyIdleSource();
    },
    onEnded: () => {
      playIntent.current = false;
      applyIdleSource();
    },
  };
  const sticker = item.kind === 'sticker';
  return shape === 'video' ? (
    <video
      {...events}
      ref={(element) => { player.current = element; }}
      aria-label={sticker ? `Стикер ${item.name}` : item.name}
      loop={sticker}
      muted={sticker}
      playsInline
      className={cn(
        'rounded-sm border border-border',
        sticker && 'max-h-40 max-w-56 object-contain',
        item.kind === 'round' && 'max-w-40',
        !sticker && item.kind !== 'round' && 'max-h-40 max-w-56',
      )}
    />
  ) : (
    <audio
      {...events}
      ref={(element) => { player.current = element; }}
      aria-label={item.name}
      className="h-9 max-w-full"
    />
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

  const images = items?.filter((item) => mediaShape(item) === 'image') ?? [];
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

  const others = items.filter((item) => mediaShape(item) !== 'image');
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
