import { Image as ImageIcon, X } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { useAttackMediaLink } from '@/hooks/useAttackMedia';
import { cn } from '@/lib/utils';
import { pluralize } from '@/lib/attacks/display';
import type { AttackImage, AttackMedia } from '@/types';

export function AttackMediaThumb({
  media,
  size = 'sm',
  onRemove,
}: {
  media: AttackImage | AttackMedia;
  size?: 'sm' | 'lg';
  onRemove?: (media: AttackImage | AttackMedia) => void;
}) {
  const link = useAttackMediaLink(media);
  const boxSize = size === 'lg' ? 'size-24' : 'size-11';

  return (
    <div
      className={cn(
        'group relative shrink-0 overflow-hidden rounded-sm border border-border bg-muted',
        boxSize,
      )}
    >
      {link.url ? (
        <a
          href={link.url}
          target="_blank"
          rel="noreferrer"
          title={media.name}
          className="block size-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={link.url}
            alt={media.name}
            loading="lazy"
            decoding="async"
            className="size-full object-cover transition-transform duration-200 group-hover:scale-105"
          />
        </a>
      ) : (
        <div
          role="img"
          className="flex size-full items-center justify-center text-muted-foreground"
          title={media.name}
          aria-label={media.name}
        >
          <ImageIcon className={size === 'lg' ? 'size-5' : 'size-4'} aria-hidden="true" />
        </div>
      )}
      {onRemove && (
        <button
          type="button"
          onClick={() => onRemove(media)}
          aria-label={`Удалить картинку ${media.name}`}
          className={cn(
            'absolute right-0.5 top-0.5 flex size-5 items-center justify-center rounded-sm',
            'border border-border bg-background/90 text-muted-foreground transition-colors',
            'hover:border-destructive/40 hover:text-destructive',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
          )}
        >
          <X className="size-3" />
        </button>
      )}
    </div>
  );
}

export function AttackMediaStrip({
  media,
  textCount,
  max = 6,
  size = 'sm',
  className,
}: {
  media: AttackImage[];
  textCount?: number;
  max?: number;
  size?: 'sm' | 'lg';
  className?: string;
}) {
  const visible = media.slice(0, max);
  const hidden = media.length - visible.length;

  if (media.length === 0 && textCount === undefined) return null;

  return (
    <div className={cn('flex flex-wrap items-center gap-2', className)}>
      {visible.map((item) => (
        <AttackMediaThumb key={item.path} media={item} size={size} />
      ))}
      {hidden > 0 && (
        <Badge variant="outline" title={`Ещё картинок: ${hidden}`}>
          +{hidden}
        </Badge>
      )}
      {textCount !== undefined && (
        <span className="font-mono text-xs text-muted-foreground">
          {textCount} {pluralize(textCount, 'текст', 'текста', 'текстов')}
        </span>
      )}
    </div>
  );
}
