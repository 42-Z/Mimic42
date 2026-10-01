import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

// ── Card ──────────────────────────────────────────────────────────────────────
// Пропсы variant/padding сохранены ради существующих вызывающих мест.
// Токены схлопнули цветовые различия вариантов (старые void-600/void-700 оба
// отображаются в border-border), поэтому bordered совпадает с default, но
// elevated сохраняет shadow-void, а glass остаётся полупрозрачным.
// Правило padding: внутри Card с CardHeader/CardContent/CardFooter передавай padding="none" — иначе p-6 задвоится.
interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'bordered' | 'elevated' | 'glass';
  padding?: 'none' | 'sm' | 'md' | 'lg';
}

const Card = React.forwardRef<HTMLDivElement, CardProps>(
  ({ className, variant = 'default', padding = 'md', children, ...props }, ref) => {
    const variants = {
      default: '',
      bordered: '',
      elevated: 'shadow-void',
      glass: 'bg-card/60 border-border/60 backdrop-blur-sm',
    };

    const paddings = {
      none: '',
      sm: 'p-4',
      md: 'p-6',
      lg: 'p-8',
    };

    return (
      <div
        ref={ref}
        className={cn(
          'rounded-sm border border-border bg-card text-card-foreground',
          // eslint-disable-next-line security/detect-object-injection -- keys are typed variant/padding unions
          variants[variant],
          // eslint-disable-next-line security/detect-object-injection -- keys are typed variant/padding unions
          paddings[padding],
          className
        )}
        {...props}
      >
        {children}
      </div>
    );
  }
);
Card.displayName = 'Card';

const CardHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('flex flex-col space-y-1.5 p-6', className)} {...props} />
  )
);
CardHeader.displayName = 'CardHeader';

interface CardTitleProps extends React.HTMLAttributes<HTMLHeadingElement> {
  /** Уровень заголовка: по умолчанию h3, как в shadcn/ui. */
  as?: 'h1' | 'h2' | 'h3' | 'h4';
}

const CardTitle = React.forwardRef<HTMLHeadingElement, CardTitleProps>(
  ({ as: Tag = 'h3', className, ...props }, ref) => (
    <Tag
      ref={ref}
      className={cn('font-mono text-base font-semibold uppercase tracking-wider text-foreground', className)}
      {...props}
    />
  )
);
CardTitle.displayName = 'CardTitle';

const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('p-6 pt-0', className)} {...props} />
  )
);
CardContent.displayName = 'CardContent';

const CardFooter = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('flex items-center p-6 pt-0', className)} {...props} />
  )
);
CardFooter.displayName = 'CardFooter';

// ── Badge ─────────────────────────────────────────────────────────────────────
const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded-[2px] px-2 py-0.5 text-xs font-mono font-medium transition-colors',
  {
    variants: {
      variant: {
        default: 'bg-muted text-foreground border border-border',
        plasma: 'bg-plasma-950 text-plasma-300 border border-plasma-800',
        neon: 'bg-neon-950 text-neon-300 border border-neon-800',
        amber: 'bg-amber-950 text-amber-300 border border-amber-800',
        crimson: 'bg-crimson-950 text-crimson-300 border border-crimson-800',
        outline: 'border border-border text-muted-foreground',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  }
);

interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

// ── Spinner ───────────────────────────────────────────────────────────────────
interface SpinnerProps {
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl';
  className?: string;
}

const spinnerSizes = {
  xs: 'h-3 w-3',
  sm: 'h-4 w-4',
  md: 'h-6 w-6',
  lg: 'h-8 w-8',
  xl: 'h-12 w-12',
};

function Spinner({ size = 'md', className }: SpinnerProps) {
  return (
    <svg
      className={cn('animate-spin text-plasma-500',
        // eslint-disable-next-line security/detect-object-injection -- key is typed size union, not user input
        spinnerSizes[size], className)}
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      aria-label="Загрузка..."
      role="status"
    >
      <circle
        className="opacity-20"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="3"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      />
    </svg>
  );
}

// ── Skeleton ──────────────────────────────────────────────────────────────────
interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: 'line' | 'block' | 'circle';
}

function Skeleton({ className, variant = 'block', ...props }: SkeletonProps) {
  return (
    <div
      className={cn(
        'relative overflow-hidden bg-muted rounded-sm',
        'after:absolute after:inset-0',
        'after:bg-gradient-to-r after:from-transparent after:via-border/50 after:to-transparent',
        'after:animate-shimmer after:bg-[length:600px_100%]',
        variant === 'circle' && 'rounded-full',
        variant === 'line' && 'h-4',
        className
      )}
      aria-hidden="true"
      {...props}
    />
  );
}

// ── Divider ───────────────────────────────────────────────────────────────────
function Divider({ className, label }: { className?: string; label?: string }) {
  if (label) {
    return (
      <div className={cn('flex items-center gap-3', className)}>
        <div className="flex-1 h-px bg-border" />
        <span className="text-xs font-mono text-muted-foreground uppercase tracking-wider">{label}</span>
        <div className="flex-1 h-px bg-border" />
      </div>
    );
  }

  return <div className={cn('h-px bg-border', className)} />;
}

export {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  CardFooter,
  Badge,
  Spinner,
  Skeleton,
  Divider,
};
