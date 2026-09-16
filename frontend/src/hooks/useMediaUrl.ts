'use client';

import { useEffect, useState } from 'react';
import { apiClient } from '@/lib/api';

/**
 * Загружает медиа-файл из логов активности (с JWT) и отдаёт object URL.
 * Object URL отзывается при размонтировании/смене пути.
 */
export function useMediaUrl(agentId: string, storagePath: string | null | undefined) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    let revoked = false;
    let created: string | null = null;
    if (!storagePath) {
      setUrl(null);
      return;
    }
    apiClient
      .get(`/agents/${agentId}/media/${storagePath}`, { responseType: 'blob' })
      .then((res) => {
        if (revoked) return;
        created = URL.createObjectURL(res.data as Blob);
        setUrl(created);
      })
      .catch(() => setUrl(null));
    return () => {
      revoked = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [agentId, storagePath]);

  return url;
}
