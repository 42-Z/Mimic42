'use client';

import { useEffect, useState } from 'react';
import { ImageOff, Loader2 } from 'lucide-react';
import { agentsApi } from '@/lib/api';
import { isDataUrl } from '@/lib/activity/media';
import { cn } from '@/lib/utils';

interface MediaThumbProps {
  agentId: string;
  reference: string;
}

/**
 * Thumbnail for a Telegram media reference from the activity log.
 * Inline data: URLs render directly; media IDs are fetched on demand
 * via GET /agents/:id/media. Expired references (HTTP 410) render a
 * plain placeholder instead of raw error JSON.
 */
export function MediaThumb({ agentId, reference }: MediaThumbProps) {
  const [url, setUrl] = useState<string | null>(isDataUrl(reference) ? reference : null);
  const [expired, setExpired] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (isDataUrl(reference)) {
      setUrl(reference);
      return;
    }
    let cancelled = false;
    let objectUrl: string | null = null;
    agentsApi
      .getMedia(agentId, reference)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        const status = (e as { status?: number })?.status;
        if (status === 410) setExpired(true);
        else setFailed(true);
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [agentId, reference]);

  if (expired || failed) {
    return (
      <div className="flex items-center gap-2 px-2.5 py-2 rounded-[2px] bg-void-900/50 border border-void-800">
        <ImageOff className="h-4 w-4 shrink-0 text-void-600" />
        <span className="font-mono text-[11px] text-void-500">
          {expired ? 'Файл устарел — Telegram больше не отдаёт его' : 'Не удалось загрузить файл'}
        </span>
      </div>
    );
  }

  if (!url) {
    return (
      <div className="flex items-center gap-2 px-2.5 py-2">
        <Loader2 className="h-4 w-4 animate-spin text-void-500" />
        <span className="font-mono text-[11px] text-void-600">Загрузка файла…</span>
      </div>
    );
  }

  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      className={cn('block max-w-64 overflow-hidden rounded-[2px] border border-void-800')}
      title="Открыть в полном размере"
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- blob/data URLs need no optimizer */}
      <img src={url} alt="Медиа из лога" className="max-h-48 w-auto object-contain bg-void-950" loading="lazy" />
    </a>
  );
}
