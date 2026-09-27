'use client';

import * as React from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from './button';

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
  size?: 'sm' | 'md' | 'lg' | 'xl';
}

const modalSizes = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-2xl',
};

export function Modal({
  isOpen,
  onClose,
  title,
  description,
  children,
  className,
  size = 'md',
}: ModalProps) {
  const contentRef = React.useRef<HTMLDivElement>(null);
  const triggerRef = React.useRef<HTMLElement | null>(null);

  // Return focus to the trigger so keyboard users keep their place. Restore is
  // done here — synchronously on unmount of the open dialog — because radix
  // defers its own restore to a setTimeout and only targets a <DialogTrigger>,
  // which this API does not use. Focus is captured once per open (in
  // onOpenAutoFocus) so parent re-renders never steal the user's Tab position.
  React.useEffect(() => {
    if (!isOpen) return;

    return () => {
      const trigger = triggerRef.current;
      triggerRef.current = null;
      if (trigger && document.contains(trigger)) {
        trigger.focus();
      }
    };
  }, [isOpen]);

  return (
    <DialogPrimitive.Root
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm animate-fade-in" />
        <DialogPrimitive.Content
          ref={contentRef}
          tabIndex={-1}
          aria-modal="true"
          onOpenAutoFocus={(event) => {
            // Remember what opened the dialog and move focus onto the panel
            // instead of the first focusable child.
            triggerRef.current =
              document.activeElement instanceof HTMLElement ? document.activeElement : null;
            event.preventDefault();
            contentRef.current?.focus();
          }}
          onCloseAutoFocus={(event) => {
            // Focus already returned to the trigger above; opt out of radix's
            // deferred restore (it would target a missing <DialogTrigger>).
            event.preventDefault();
          }}
          className={cn(
            'fixed left-1/2 top-1/2 z-50 w-full -translate-x-1/2 -translate-y-1/2',
            'rounded-sm border border-border bg-card shadow-void-lg animate-dialog-in',
            'focus:outline-none',
            // eslint-disable-next-line security/detect-object-injection -- key is typed size union, not user input
            modalSizes[size],
            className
          )}
        >
          {/* Scan line decoration */}
          <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-primary/50 to-transparent" />

          {/* Диалог всегда имеет заголовок: без видимого title рендерим скрытый,
              чтобы aria-имя не зависело от запасного aria-label. */}
          {!title && (
            <DialogPrimitive.Title className="sr-only">Диалог</DialogPrimitive.Title>
          )}

          {/* Header */}
          {(title || description) && (
            <div className="px-6 pt-6 pb-4 border-b border-border">
              {title && (
                <DialogPrimitive.Title
                  className="font-mono text-base font-semibold text-foreground uppercase tracking-wider"
                >
                  {title}
                </DialogPrimitive.Title>
              )}
              {description && (
                <DialogPrimitive.Description
                  className="mt-1 text-sm text-muted-foreground font-mono"
                >
                  {description}
                </DialogPrimitive.Description>
              )}
            </div>
          )}

          {/* Body */}
          <div className="p-6">{children}</div>

          {/* Close button */}
          <DialogPrimitive.Close
            className={cn(
              'absolute top-4 right-4',
              'h-7 w-7 flex items-center justify-center',
              'text-muted-foreground hover:text-foreground',
              'transition-colors duration-150',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
              'font-mono text-lg'
            )}
            aria-label="Закрыть"
          >
            <X className="h-4 w-4" />
          </DialogPrimitive.Close>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

// ── Confirm Dialog ────────────────────────────────────────────────────────────
interface ConfirmDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: 'danger' | 'default';
  isLoading?: boolean;
}

export function ConfirmDialog({
  isOpen,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel = 'Подтвердить',
  cancelLabel = 'Отмена',
  variant = 'default',
  isLoading,
}: ConfirmDialogProps) {
  return (
    <Modal isOpen={isOpen} onClose={onClose} title={title} description={description} size="sm">
      <div className="flex justify-end gap-3 mt-2">
        <Button variant="ghost" size="sm" onClick={onClose} disabled={isLoading}>
          {cancelLabel}
        </Button>
        <Button
          variant={variant}
          size="sm"
          onClick={onConfirm}
          isLoading={isLoading}
        >
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}
