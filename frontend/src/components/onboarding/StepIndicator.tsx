import { cn } from '@/lib/utils';
import type { OnboardingStep } from '@/types';

const STEPS: { id: OnboardingStep; label: string; short: string }[] = [
  { id: 'name',                label: 'Имя агента',       short: '01' },
  { id: 'soul',                label: 'Характер',          short: '02' },
  { id: 'telegram_credentials',label: 'Telegram',          short: '03' },
  { id: 'finalize',            label: 'Финализация',       short: '04' },
];

// Steps that count as "telegram" phase
const TELEGRAM_STEPS: OnboardingStep[] = [
  'telegram_credentials', 'telegram_code', 'telegram_2fa',
];

function getStepIndex(step: OnboardingStep): number {
  if (TELEGRAM_STEPS.includes(step)) {
    return STEPS.findIndex((s) => s.id === 'telegram_credentials');
  }
  return STEPS.findIndex((s) => s.id === step);
}

interface StepIndicatorProps {
  currentStep: OnboardingStep;
  className?: string;
}

export function StepIndicator({ currentStep, className }: StepIndicatorProps) {
  const currentIndex = getStepIndex(currentStep);

  return (
    <div className={cn('flex items-center gap-0', className)} data-testid="step-indicator">
      {STEPS.map((step, index) => {
        const isDone = index < currentIndex;
        const isActive = index === currentIndex;

        return (
          <div key={step.id} className="flex items-center" data-testid={`onboarding-step-${step.id}`}>
            {/* Node */}
            <div className="flex flex-col items-center">
              <div className={cn(
                'h-8 w-8 rounded-sm flex items-center justify-center',
                'font-mono text-xs font-bold transition-all duration-300',
                'border',
                isDone && 'bg-neon-900 border-neon-700 text-neon-400',
                isActive && 'bg-plasma-900 border-plasma-600 text-plasma-300 shadow-plasma-sm',
                !isDone && !isActive && 'bg-void-800 border-void-700 text-void-600',
              )}>
                {isDone ? '✓' : step.short}
              </div>
              <span className={cn(
                'font-mono text-[10px] mt-1.5 text-center w-16 leading-tight',
                isActive ? 'text-plasma-400' : isDone ? 'text-neon-600' : 'text-void-600',
              )}>
                {step.label}
              </span>
            </div>

            {/* Connector */}
            {index < STEPS.length - 1 && (
              <div className={cn(
                'h-px w-8 sm:w-12 mb-5 transition-all duration-300',
                index < currentIndex ? 'bg-neon-700' : 'bg-void-800',
              )} />
            )}
          </div>
        );
      })}
    </div>
  );
}
