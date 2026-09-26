import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const buttonVariants = cva(
  [
    'inline-flex items-center justify-center gap-2',
    'font-mono text-sm font-medium rounded-sm border',
    'transition-all duration-150 ease-spring',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
    'disabled:pointer-events-none disabled:opacity-40',
    'active:scale-[0.97] select-none',
  ],
  {
    variants: {
      variant: {
        default: ['bg-primary border-primary text-primary-foreground', 'hover:bg-primary/90 hover:shadow-plasma-sm'],
        secondary: ['bg-secondary border-border text-secondary-foreground', 'hover:bg-muted'],
        ghost: ['bg-transparent border-transparent text-muted-foreground', 'hover:bg-muted hover:text-foreground'],
        danger: ['bg-destructive border-destructive text-destructive-foreground', 'hover:bg-destructive/90 hover:shadow-crimson'],
        success: ['bg-success border-success text-white', 'hover:bg-success/90 hover:shadow-neon-sm'],
        outline: ['bg-transparent border-border text-foreground', 'hover:bg-muted hover:border-primary/60 hover:text-primary'],
        'plasma-outline': ['bg-transparent border-primary/50 text-primary', 'hover:bg-primary/10 hover:border-primary hover:text-primary/90 hover:shadow-plasma-sm'],
      },
      size: {
        xs: 'h-6 px-2 text-xs', sm: 'h-8 px-3 text-xs', md: 'h-9 px-4', lg: 'h-11 px-6 text-base',
        xl: 'h-13 px-8 text-base', icon: 'h-9 w-9 p-0', 'icon-sm': 'h-7 w-7 p-0', 'icon-lg': 'h-11 w-11 p-0',
      },
      loading: { true: 'cursor-wait', false: '' },
    },
    defaultVariants: { variant: 'default', size: 'md', loading: false },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  isLoading?: boolean; leftIcon?: React.ReactNode; rightIcon?: React.ReactNode; asChild?: boolean;
}

const Spinner = ({ className }: { className?: string }) => (
  <svg className={cn('animate-spin', className)} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" aria-hidden="true">
    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
  </svg>
);

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, isLoading, loading: _loading, leftIcon, rightIcon, children, disabled, asChild = false, ...props }, ref) => {
    const isDisabled = disabled || isLoading;
    const Comp = asChild ? Slot : 'button';
    return (
      <Comp ref={ref} className={cn(buttonVariants({ variant, size, loading: isLoading }), className)} disabled={isDisabled} aria-disabled={isDisabled} {...props}>
        {isLoading ? <Spinner className="h-4 w-4" /> : leftIcon ? <span className="shrink-0">{leftIcon}</span> : null}
        {children}
        {!isLoading && rightIcon ? <span className="shrink-0">{rightIcon}</span> : null}
      </Comp>
    );
  }
);
Button.displayName = 'Button';
export { Button, buttonVariants };
