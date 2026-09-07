import * as React from 'react';
import { cn } from '@/lib/utils';

// ── Input ─────────────────────────────────────────────────────────────────────
export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  error?: string;
  label?: string;
  hint?: string;
  leftElement?: React.ReactNode;
  rightElement?: React.ReactNode;
}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, error, label, hint, leftElement, rightElement, id, ...props }, ref) => {
    const inputId = id ?? label?.toLowerCase().replace(/\s+/g, '-');

    return (
      <div className="flex flex-col gap-1.5">
        {label && (
          <label
            htmlFor={inputId}
            className="text-xs font-mono font-medium text-void-300 uppercase tracking-wider"
          >
            {label}
          </label>
        )}
        <div className="relative flex items-center">
          {leftElement && (
            <div className="absolute left-3 flex items-center pointer-events-none text-void-400">
              {leftElement}
            </div>
          )}
          <input
            id={inputId}
            type={type}
            className={cn(
              'flex h-10 w-full rounded-sm',
              'bg-void-800 border border-void-600',
              'px-3 py-2',
              'font-mono text-base sm:text-sm text-void-100',
              'placeholder:text-void-500',
              'transition-colors duration-150',
              'focus:outline-none focus:ring-1 focus:ring-plasma-500 focus:border-plasma-600',
              'hover:border-void-500',
              'disabled:cursor-not-allowed disabled:opacity-50',
              'autofill:bg-void-800',
              error && 'border-crimson-600 focus:ring-crimson-500 focus:border-crimson-500',
              leftElement && 'pl-9',
              rightElement && 'pr-9',
              className
            )}
            ref={ref}
            aria-invalid={error ? 'true' : undefined}
            aria-describedby={error ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined}
            {...props}
          />
          {rightElement && (
            <div className="absolute right-1 flex min-h-[44px] min-w-[44px] items-center justify-center text-void-400">
              {rightElement}
            </div>
          )}
        </div>
        {error && (
          <p
            id={`${inputId}-error`}
            className="text-xs text-crimson-400 font-mono flex items-center gap-1"
            role="alert"
          >
            <span aria-hidden="true">✗</span>
            {error}
          </p>
        )}
        {hint && !error && (
          <p id={`${inputId}-hint`} className="text-xs text-void-500 font-mono">
            {hint}
          </p>
        )}
      </div>
    );
  }
);
Input.displayName = 'Input';

// ── Textarea ──────────────────────────────────────────────────────────────────
export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  error?: string;
  label?: string;
  hint?: string;
  showCount?: boolean;
  maxLength?: number;
}

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, error, label, hint, showCount, maxLength, id, value, ...props }, ref) => {
    const textareaId = id ?? label?.toLowerCase().replace(/\s+/g, '-');
    const charCount = typeof value === 'string' ? value.length : 0;

    return (
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          {label && (
            <label
              htmlFor={textareaId}
              className="text-xs font-mono font-medium text-void-300 uppercase tracking-wider"
            >
              {label}
            </label>
          )}
          {showCount && maxLength && (
            <span
              className={cn(
                'text-xs font-mono tabular-nums',
                charCount > maxLength * 0.9 ? 'text-amber-400' : 'text-void-500',
                charCount >= maxLength && 'text-crimson-400'
              )}
            >
              {charCount.toLocaleString()} / {maxLength.toLocaleString()}
            </span>
          )}
        </div>
        <textarea
          id={textareaId}
          className={cn(
            'flex w-full rounded-sm',
            'bg-void-800 border border-void-600',
            'px-3 py-2.5',
            'font-mono text-base sm:text-sm text-void-100',
            'placeholder:text-void-500',
            'transition-colors duration-150',
            'focus:outline-none focus:ring-1 focus:ring-plasma-500 focus:border-plasma-600',
            'hover:border-void-500',
            'disabled:cursor-not-allowed disabled:opacity-50',
            'resize-y min-h-[100px]',
            error && 'border-crimson-600 focus:ring-crimson-500 focus:border-crimson-500',
            className
          )}
          ref={ref}
          value={value}
          maxLength={maxLength}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={
            error ? `${textareaId}-error` : hint ? `${textareaId}-hint` : undefined
          }
          {...props}
        />
        {error && (
          <p
            id={`${textareaId}-error`}
            className="text-xs text-crimson-400 font-mono flex items-center gap-1"
            role="alert"
          >
            <span aria-hidden="true">✗</span>
            {error}
          </p>
        )}
        {hint && !error && (
          <p id={`${textareaId}-hint`} className="text-xs text-void-500 font-mono">
            {hint}
          </p>
        )}
      </div>
    );
  }
);
Textarea.displayName = 'Textarea';

// ── Label ─────────────────────────────────────────────────────────────────────
const Label = React.forwardRef<
  HTMLLabelElement,
  React.LabelHTMLAttributes<HTMLLabelElement>
>(({ className, ...props }, ref) => (
  <label
    ref={ref}
    className={cn(
      'text-xs font-mono font-medium text-void-300 uppercase tracking-wider',
      'peer-disabled:cursor-not-allowed peer-disabled:opacity-70',
      className
    )}
    {...props}
  />
));
Label.displayName = 'Label';

export { Input, Textarea, Label };
