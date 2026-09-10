'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import type { Toast, ToastVariant } from '@/types';

// ── Context ───────────────────────────────────────────────────────────────────
interface ToastContextValue {
  toasts: Toast[];
  toast: (message: string, variant?: ToastVariant, duration?: number) => void;
  dismiss: (id: string) => void;
  dismissAll: () => void;
}

const ToastContext = React.createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = React.useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within <ToastProvider>');
  return ctx;
}

// ── Provider ──────────────────────────────────────────────────────────────────
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([]);

  const dismiss = React.useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const dismissAll = React.useCallback(() => {
    setToasts([]);
  }, []);

  const toast = React.useCallback(
    (message: string, variant: ToastVariant = 'info', duration = 4000) => {
      const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      const newToast: Toast = { id, message, variant, duration };

      setToasts((prev) => {
        // Max 5 toasts at once
        const updated = [...prev, newToast];
        return updated.slice(-5);
      });

      if (duration > 0) {
        setTimeout(() => dismiss(id), duration);
      }
    },
    [dismiss]
  );

  return (
    <ToastContext.Provider value={{ toasts, toast, dismiss, dismissAll }}>
      {children}
      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

// ── Individual Toast ───────────────────────────────────────────────────────────
const variantStyles: Record<ToastVariant, string> = {
  success: 'border-neon-700 bg-neon-950/90 text-neon-200',
  error:   'border-crimson-700 bg-crimson-950/90 text-crimson-200',
  warning: 'border-amber-700 bg-amber-950/90 text-amber-200',
  info:    'border-plasma-700 bg-plasma-950/90 text-plasma-200',
};

const variantIcons: Record<ToastVariant, string> = {
  success: '✓',
  error:   '✗',
  warning: '⚠',
  info:    'ℹ',
};

interface ToastItemProps {
  toast: Toast;
  onDismiss: (id: string) => void;
}

function ToastItem({ toast, onDismiss }: ToastItemProps) {
  const [isLeaving, setIsLeaving] = React.useState(false);

  const handleDismiss = () => {
    setIsLeaving(true);
    setTimeout(() => onDismiss(toast.id), 200);
  };

  return (
    <div
      className={cn(
        'relative flex items-start gap-3 min-w-[300px] max-w-[420px]',
        'px-4 py-3 rounded-sm border',
        'backdrop-blur-sm shadow-void',
        'font-mono text-sm',
        variantStyles[toast.variant],
        isLeaving
          ? 'animate-[fadeOut_0.2s_ease-in_forwards]'
          : 'animate-slide-in-right',
      )}
      role="alert"
      aria-live="assertive"
      aria-atomic="true"
    >
      <span className="shrink-0 font-bold mt-px" aria-hidden="true">
        {variantIcons[toast.variant]}
      </span>
      <p className="flex-1 leading-relaxed break-words">{toast.message}</p>
      <button
        onClick={handleDismiss}
        className="shrink-0 ml-2 opacity-60 hover:opacity-100 transition-opacity text-current"
        aria-label="Закрыть уведомление"
      >
        ×
      </button>
    </div>
  );
}

// ── Container ─────────────────────────────────────────────────────────────────
function ToastContainer({
  toasts,
  onDismiss,
}: {
  toasts: Toast[];
  onDismiss: (id: string) => void;
}) {
  if (toasts.length === 0) return null;

  return (
    <div
      data-testid="toast-container"
      className="fixed bottom-4 right-4 z-[9999] flex flex-col gap-2 pointer-events-none"
      aria-label="Уведомления"
    >
      {toasts.map((t) => (
        <div key={t.id} className="pointer-events-auto">
          <ToastItem toast={t} onDismiss={onDismiss} />
        </div>
      ))}
    </div>
  );
}
