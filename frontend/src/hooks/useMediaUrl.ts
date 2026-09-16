'use client';

import { useEffect, useState } from 'react';
import { apiClient } from '@/lib/api';

export type MediaUrlStatus = 'idle' | 'loading' | 'ready' | 'error';

export interface MediaUrlResult {
  url: string | null;
  status: MediaUrlStatus;
}

/**
 * Загружает медиа-файл из логов активности (с JWT) и отдаёт object URL.
 * Object URL отзывается при размонтировании/смене пути; ошибки загрузки
 * отличимы от состояния «идёт загрузка».
 */
export function useMediaUrl(agentId: string, storagePath: string | null | undefined): MediaUrlResult {
  const [result, setResult] = useState<MediaUrlResult>({ url: null, status: 'idle' });

  useEffect(() => {
    let revoked = false;
    let created: string | null = null;
    if (!storagePath || !agentId) {
      setResult({ url: null, status: 'idle' });
      return;
    }
    setResult({ url: null, status: 'loading' });
    apiClient
      .get(`/agents/${agentId}/media/${storagePath}`, { responseType: 'blob' })
      .then((res) => {
        if (revoked) return;
        created = URL.createObjectURL(res.data as Blob);
        setResult({ url: created, status: 'ready' });
      })
      .catch(() => {
        if (revoked) return;
        setResult({ url: null, status: 'error' });
      });
    return () => {
      revoked = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [agentId, storagePath]);

  return result;
}
