'use client';

import * as React from 'react';
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
  // Close on Escape key
  React.useEffect(() => {
    if (!isOpen) return;

    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKey);

    // Lock body scroll
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', handleKey);
      document.body.style.overflow = '';
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby={title ? 'modal-title' : undefined}
      aria-describedby={description ? 'modal-description' : undefined}
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-void-950/80 backdrop-blur-sm animate-fade-in"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Panel */}
      <div
        className={cn(
          'relative w-full z-10',
          'bg-void-800 border border-void-600',
          'rounded-sm shadow-void-lg',
          'animate-slide-in-up',
          // eslint-disable-next-line security/detect-object-injection -- key is typed size union, not user input
          modalSizes[size],
          className
        )}
      >
        {/* Scan line decoration */}
        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-plasma-500/50 to-transparent" />

        {/* Header */}
        {(title || description) && (
          <div className="px-6 pt-6 pb-4 border-b border-void-700">
            {title && (
              <h2
                id="modal-title"
                className="font-mono text-base font-semibold text-void-100 uppercase tracking-wider"
              >
                {title}
              </h2>
            )}
            {description && (
              <p id="modal-description" className="mt-1 text-sm text-void-400 font-mono">
                {description}
              </p>
            )}
          </div>
        )}

        {/* Body */}
        <div className="p-6">{children}</div>

        {/* Close button */}
        <button
          onClick={onClose}
          className={cn(
            'absolute top-4 right-4',
            'h-7 w-7 flex items-center justify-center',
            'text-void-500 hover:text-void-200',
            'transition-colors duration-150',
            'font-mono text-lg'
          )}
          aria-label="Закрыть"
        >
          ×
        </button>
      </div>
    </div>
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
          variant={variant === 'danger' ? 'danger' : 'default'}
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
