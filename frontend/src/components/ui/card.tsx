import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

// ── Card ──────────────────────────────────────────────────────────────────────
interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'bordered' | 'elevated' | 'glass';
  padding?: 'none' | 'sm' | 'md' | 'lg';
}

const Card = React.forwardRef<HTMLDivElement, CardProps>(
  ({ className, variant = 'default', padding = 'md', children, ...props }, ref) => {
    const variants = {
      default: 'bg-void-800 border border-void-700',
      bordered: 'bg-void-800 border border-void-600',
      elevated: 'bg-void-800 border border-void-700 shadow-void',
      glass: 'bg-void-900/60 backdrop-blur-sm border border-void-700/60',
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
          'rounded-sm',
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
    <div ref={ref} className={cn('flex flex-col gap-1.5', className)} {...props} />
  )
);
CardHeader.displayName = 'CardHeader';

const CardTitle = React.forwardRef<HTMLHeadingElement, React.HTMLAttributes<HTMLHeadingElement>>(
  ({ className, children, ...props }, ref) => (
    <h3
      ref={ref}
      className={cn('font-mono text-sm font-medium text-void-200 uppercase tracking-wider', className)}
      {...props}
    >
      {children}
    </h3>
  )
);
CardTitle.displayName = 'CardTitle';

const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('', className)} {...props} />
  )
);
CardContent.displayName = 'CardContent';

const CardFooter = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('flex items-center pt-4 border-t border-void-700', className)} {...props} />
  )
);
CardFooter.displayName = 'CardFooter';

// ── Badge ─────────────────────────────────────────────────────────────────────
const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded-[2px] px-2 py-0.5 text-xs font-mono font-medium transition-colors',
  {
    variants: {
      variant: {
        default: 'bg-void-700 text-void-200 border border-void-600',
        plasma: 'bg-plasma-950 text-plasma-300 border border-plasma-800',
        neon: 'bg-neon-950 text-neon-300 border border-neon-800',
        amber: 'bg-amber-950 text-amber-300 border border-amber-800',
        crimson: 'bg-crimson-950 text-crimson-300 border border-crimson-800',
        outline: 'border border-void-600 text-void-300',
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
        'relative overflow-hidden bg-void-800 rounded-sm',
        'after:absolute after:inset-0',
        'after:bg-gradient-to-r after:from-transparent after:via-void-700/50 after:to-transparent',
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
        <div className="flex-1 h-px bg-void-700" />
        <span className="text-xs font-mono text-void-500 uppercase tracking-wider">{label}</span>
        <div className="flex-1 h-px bg-void-700" />
      </div>
    );
  }

  return <div className={cn('h-px bg-void-700', className)} />;
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
