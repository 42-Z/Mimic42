# Shadcn Redesign (Issue #102) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the entire Mimic42 frontend from hand-rolled Tailwind primitives to shadcn/ui components while preserving and elevating the dark "terminal" visual world (void/plasma/neon/crimson), keeping all behaviour and tests green.

**Architecture:** Adopt shadcn/radix as the *implementation base* for every `components/ui/*` primitive, but keep the app-facing module paths, export names, and prop signatures that ~25 call sites and the `bun test` suite depend on. shadcn semantic tokens (RGB-triplet CSS variables) are layered over the existing palette so both `bg-void-950` utility classes and shadcn components theme correctly. Each screen then inherits the new primitives and gets a targeted craft-elevation pass (hierarchy, spacing rhythm, states, a11y).

**Tech Stack:** Next.js 14 (App Router, TypeScript), Tailwind CSS v3.4, shadcn/ui (radix primitives + cva), class-variance-authority, tailwind-merge, lucide-react, bun (test runner), Supabase (auth). Design methodology: Impeccable (PRODUCT.md already written; DESIGN.md written at the end).

**Overriding constraints (from PRODUCT.md + issue #102):**
- The dark aesthetic is a **binding brand constraint** — develop it, never replace it with a light theme or a different world.
- `api_hash`, `phone_code_hash`, Telethon `StringSession` are backend secrets — **never** render them into the UI.
- Both user segments (individuals + teams) matter; the UI must work for 1..N agents.
- Preserve behaviour and keep `bunx tsc --noEmit`, `bun test`, `next build`, and e2e green.

---

## Approach & Locked Decisions

These are decided so the executor never re-litigates them:

1. **Token model = shadcn Tailwind-v3 convention with RGB triplets.** CSS variables hold space-separated RGB (e.g. `--primary: 26 127 255`) and `tailwind.config.ts` maps them as `rgb(var(--primary) / <alpha-value>)`. This preserves the exact dark-world hexes and keeps opacity modifiers working. (Not HSL — avoids conversion drift.)
2. **Keep the existing `void / plasma / neon / crimson / amber` palettes** in `tailwind.config.ts` alongside the new semantic tokens. Existing `bg-void-950` etc. keep compiling; screens migrate to semantic tokens only where it improves consistency. This is deliberate — it keeps the diff reviewable and the tests stable.
3. **"shadcn internals, stable app API."** Leaf primitives keep their exact export names/props. `Modal`/`ConfirmDialog` are re-implemented over **radix `Dialog`**; `useToast`/`ToastProvider` keep the context + `toasts`/`dismiss`/`dismissAll` contract (and `data-testid="toast-container"`) while the visual `ToastItem` is rebuilt on shadcn toast tokens. This is genuine shadcn under the hood without breaking the `modal-focus.test.tsx` / `reset-context-dialog.test.tsx` contracts.
4. **Do NOT switch to sonner's `toast()` API.** It would rewrite 12 call sites and break the toast test contract. Out of scope for this PR (a follow-up can do it).
5. **Package runner is bun.** shadcn commands run as `bunx --bun shadcn@latest ...`. The project has no `components.json` yet; `init` creates it.
6. **One PR** for the whole redesign, built on branch `shadcn-issue102` (already synced to `main`).

## File Structure

New / primary:
- `frontend/components.json` — shadcn config (created by `init`).
- `frontend/src/app/globals.css` — add `@layer base` shadcn token block (Modify).
- `frontend/tailwind.config.ts` — add semantic token colors + radius (Modify).
- `frontend/src/components/ui/*.tsx` — 5 primitives re-based on shadcn/radix (Modify in place; paths unchanged).
- `docs/plans/DESIGN.md` — written at the end (Task 12).

Screens (Modify):
- Layout: `frontend/src/components/layout/{Header,Sidebar}.tsx`, `frontend/src/app/(dashboard)/layout.tsx`.
- Auth: `frontend/src/app/(auth)/{login,register,reset-password,update-password}/page.tsx`.
- Dashboard: `frontend/src/app/(dashboard)/dashboard/page.tsx`, `frontend/src/components/agents/*`.
- Agent: `frontend/src/app/(dashboard)/agent/[id]/page.tsx`, `frontend/src/components/agent/*`, `frontend/src/components/activity/*`.
- Onboarding/Rebind: `frontend/src/app/(dashboard)/onboarding/page.tsx`, `frontend/src/app/(dashboard)/agent/[id]/rebind/page.tsx`, `frontend/src/components/agent/RebindPageClient.tsx`, `frontend/src/components/agent/ResetContextDialog.tsx`.

Tests to keep green (Modify only if the migration forces it):
- `frontend/src/__tests__/modal-focus.test.tsx`, `reset-context-dialog.test.tsx`, `agent-toggle-button.test.tsx`, `preset-picker.test.tsx`, `token-usage-card.test.tsx`, `telegram-session-details.test.tsx`.

---

## Migration Pattern (referenced by screen tasks)

A screen "elevation" pass applies this exact checklist. Work through it top-to-bottom on the target JSX; every change is a className/structure edit. The reference example is the auth card (Task 8). Where a screen's edit is non-obvious, that screen's task shows the concrete code inline.

1. **Imports** — point at `@/components/ui/*` (unchanged paths). Where a screen used raw `<button>`/`<input>`/`<div role="dialog">`, switch to the `Button`/`Input`/`Modal` primitives.
2. **Semantic tokens** — replace raw `bg-void-800 border-void-600` card surfaces with `bg-card border-border`, body text `text-void-100`→`text-foreground`, secondary text `text-void-400`→`text-muted-foreground`. Keep `plasma/neon/crimson/amber` for accents/status.
3. **Type hierarchy** — one display face (Syne) for headings, Space Mono for labels/data/IDs (the terminal voice), body text on the sans stack. Section titles → `font-mono uppercase tracking-wider text-muted-foreground text-xs`.
4. **Spacing rhythm** — `space-y-*` between blocks, more space above a heading than below it; card padding `p-6`, dense rows `px-4 py-3`. `rounded-sm` stays (the terminal look keeps sharp corners); `--radius` token is `0.25rem`.
5. **States** — every interactive element gets `focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background`, `disabled:opacity-40`, `active:scale-[0.98]` where the existing design already scales.
6. **Empty / loading / error** — keep the existing `Skeleton`/`Spinner` usage; ensure empty states have a real message (Impeccable craft floor: no dead panes).
7. **A11y** — `aria-label` on icon-only controls, `aria-live` on toasts, labelled inputs, `role`/`aria-modal` on dialogs (radix provides this on `Modal`).
8. **Run** `bunx tsc --noEmit && bun test` before committing the screen.

---

## Task 1: shadcn init + dependencies

**Files:**
- Create: `frontend/components.json` (generated)
- Modify: `frontend/package.json` (adds radix deps)
- Modify: `frontend/tsconfig.json` (ensure `@/*` alias → `./src/*`)

- [ ] **Step 1: Confirm the `@/*` path alias**

Run: `grep -n '"@/\*"' frontend/tsconfig.json`
Expected: a `paths` entry `"@/*": ["./src/*"]`. If absent, add it (shadcn writes to `@/components/ui/...` which must resolve into `src/`).

- [ ] **Step 2: Initialise shadcn non-interactively**

```bash
cd frontend
bunx --bun shadcn@latest init --yes --template next --preset base-nova
```
Expected: creates `components.json` and installs base deps. **Immediately verify `shadcn init` did not clobber our theme:** run `git diff -- src/app/globals.css tailwind.config.ts`. If it dropped the `@tailwind base/components/utilities` directives or the `void/plasma/neon/crimson/amber` palette, `git checkout -- src/app/globals.css tailwind.config.ts` to restore them (Task 2 writes the final token block deliberately). Do **not** ship a light/default theme.

- [ ] **Step 3: Install the two radix deps the later primitives need**

Task 3's `Button` uses `@radix-ui/react-slot` (asChild); Task 6's `Modal` imports `@radix-ui/react-dialog` directly (we write `modal.tsx` by hand — we do NOT use a generated `dialog.tsx`, which would drag in the redundant `radix-ui` + `cn` packages and Tailwind-v4 idioms that are inert in our v3 build). So install just the two scoped radix packages:

```bash
bun add @radix-ui/react-dialog @radix-ui/react-slot
```
Expected: `@radix-ui/react-dialog` and `@radix-ui/react-slot` in `package.json`. If `shadcn init` generated `src/components/ui/dialog.tsx` or added `radix-ui`/`cn` packages, **delete `src/components/ui/dialog.tsx` and `bun remove radix-ui cn`** — nothing imports them, and the project's single `cn` is `@/lib/utils` (`twMerge(clsx())`). (`clsx`, `tailwind-merge`, `class-variance-authority`, `lucide-react` are already in `package.json`.)

- [ ] **Step 4: Verify the tree is still green (nothing was overwritten)**

Run: `cd frontend && bunx tsc --noEmit && bun test`
Expected: PASS. This is the gate — because we did not overwrite `button/card/input/...`, the existing suite must still pass.

Run: `grep -E "radix|class-variance|tailwind-merge|clsx|lucide" frontend/package.json`
Expected: `@radix-ui/react-dialog`, `@radix-ui/react-slot` present alongside the existing `clsx`/`tailwind-merge`/`class-variance-authority`/`lucide-react`; NO `radix-ui` or `cn` packages; NO generated `dialog.tsx`.

- [ ] **Step 5: Commit**

```bash
git add frontend/components.json frontend/package.json frontend/bun.lock frontend/tsconfig.json
git commit -m "chore(frontend): initialise shadcn/ui and radix deps"
```

---

## Task 2: Design tokens (dark world → shadcn semantics)

**Files:**
- Modify: `frontend/src/app/globals.css`
- Modify: `frontend/tailwind.config.ts`

- [ ] **Step 1: Add the shadcn token block to `globals.css`**

Insert into the `@layer base` `:root` block (RGB triplets keep the exact dark-world colors and support `/opacity`). Keep the existing `--font-*` vars and body rules.

```css
  :root {
    --font-geist-sans: 'Syne', system-ui, sans-serif;
    --font-geist-mono: 'Space Mono', monospace;
    --font-display: 'Syne', system-ui, sans-serif;

    /* shadcn semantic tokens — dark "terminal" world (void/plasma/neon/crimson) */
    --background: 5 5 14;            /* void-950 */
    --foreground: 224 224 229;       /* void-100 */
    --card: 18 18 32;                /* void-800 */
    --card-foreground: 224 224 229;
    --popover: 18 18 32;
    --popover-foreground: 224 224 229;
    --primary: 26 127 255;           /* plasma-500 */
    --primary-foreground: 255 255 255;
    --secondary: 37 37 53;           /* void-600 */
    --secondary-foreground: 224 224 229;
    --muted: 26 26 40;               /* void-700 */
    --muted-foreground: 144 144 160; /* void-300 */
    --accent: 37 37 53;
    --accent-foreground: 224 224 229;
    --destructive: 244 63 94;        /* crimson-500 */
    --destructive-foreground: 255 255 255;
    --success: 0 224 112;            /* neon-500 */
    --warning: 245 158 11;           /* amber-500 */
    --border: 37 37 53;
    --input: 37 37 53;
    --ring: 26 127 255;
    --radius: 0.25rem;
  }
```

- [ ] **Step 2: Point body at the semantic tokens**

Change the `body` rule's `@apply` line to use the token utilities so the whole app sits on the same ground:

```css
  body {
    @apply bg-background text-foreground antialiased;
    font-family: var(--font-geist-sans);
    background-image:
      linear-gradient(rgba(26, 127, 255, 0.03) 1px, transparent 1px),
      linear-gradient(90deg, rgba(26, 127, 255, 0.03) 1px, transparent 1px);
    background-size: 40px 40px;
  }
```

- [ ] **Step 3: Add semantic colors to `tailwind.config.ts`**

Inside `theme.extend.colors`, **add** (do not remove `void/plasma/neon/crimson/amber`):

```ts
        background: 'rgb(var(--background) / <alpha-value>)',
        foreground: 'rgb(var(--foreground) / <alpha-value>)',
        card: { DEFAULT: 'rgb(var(--card) / <alpha-value>)', foreground: 'rgb(var(--card-foreground) / <alpha-value>)' },
        popover: { DEFAULT: 'rgb(var(--popover) / <alpha-value>)', foreground: 'rgb(var(--popover-foreground) / <alpha-value>)' },
        primary: { DEFAULT: 'rgb(var(--primary) / <alpha-value>)', foreground: 'rgb(var(--primary-foreground) / <alpha-value>)' },
        secondary: { DEFAULT: 'rgb(var(--secondary) / <alpha-value>)', foreground: 'rgb(var(--secondary-foreground) / <alpha-value>)' },
        muted: { DEFAULT: 'rgb(var(--muted) / <alpha-value>)', foreground: 'rgb(var(--muted-foreground) / <alpha-value>)' },
        accent: { DEFAULT: 'rgb(var(--accent) / <alpha-value>)', foreground: 'rgb(var(--accent-foreground) / <alpha-value>)' },
        destructive: { DEFAULT: 'rgb(var(--destructive) / <alpha-value>)', foreground: 'rgb(var(--destructive-foreground) / <alpha-value>)' },
        success: 'rgb(var(--success) / <alpha-value>)',
        warning: 'rgb(var(--warning) / <alpha-value>)',
        border: 'rgb(var(--border) / <alpha-value>)',
        input: 'rgb(var(--input) / <alpha-value>)',
        ring: 'rgb(var(--ring) / <alpha-value>)',
```

And inside `theme.extend` add `borderRadius`:

```ts
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
```

- [ ] **Step 4: Verify tokens resolve**

Run: `cd frontend && bunx tsc --noEmit && bun test`
Expected: PASS (no test touches the token names yet; this proves nothing broke).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/globals.css frontend/tailwind.config.ts
git commit -m "feat(frontend): shadcn semantic tokens over the dark world"
```

---

## Task 3: Button → shadcn

**Files:**
- Modify: `frontend/src/components/ui/button.tsx`

- [ ] **Step 1: Re-base `Button` on `@radix-ui/react-slot` + cva, keeping the exact public API**

Keep the exports `Button`, `buttonVariants` and props `isLoading`, `leftIcon`, `rightIcon`, and the7 variants + 8 sizes. Replace the internal `<button>` with `Slot`-capable shadcn structure and the token-based focus ring. Full replacement:

```tsx
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
  ({ className, variant, size, isLoading, leftIcon, rightIcon, children, disabled, asChild = false, ...props }, ref) => {
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
```

- [ ] **Step 2: Verify**

Run: `cd frontend && bunx tsc --noEmit && bun test`
Expected: PASS. `agent-toggle-button.test.tsx` exercises `Button`/`buttonVariants` — must stay green.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/button.tsx
git commit -m "refactor(frontend): Button onto shadcn Slot + semantic tokens"
```

---

## Task 4: Card / Badge / Spinner / Skeleton → shadcn

**Files:**
- Modify: `frontend/src/components/ui/card.tsx`

- [ ] **Step 1: Re-base the Card family on shadcn Card + tokens, keep `Badge`, `Spinner`, `Skeleton` exports**

Keep export names `Card, CardHeader, CardTitle, CardContent, CardFooter, Badge, Spinner, Skeleton` (call sites import these exact names, e.g. `import { Card, Skeleton, Spinner, Divider } from '@/components/ui/card'` — also keep `Divider`). Structure:

```tsx
import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('rounded-sm border border-border bg-card text-card-foreground shadow-void', className)} {...props} />
  )
);
Card.displayName = 'Card';

const CardHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => <div ref={ref} className={cn('flex flex-col space-y-1.5 p-6', className)} {...props} />
);
CardHeader.displayName = 'CardHeader';

const CardTitle = React.forwardRef<HTMLHeadingElement, React.HTMLAttributes<HTMLHeadingElement>>(
  ({ className, ...props }, ref) => (
    <h3 ref={ref} className={cn('font-mono text-base font-semibold uppercase tracking-wider text-foreground', className)} {...props} />
  )
);
CardTitle.displayName = 'CardTitle';

const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => <div ref={ref} className={cn('p-6 pt-0', className)} {...props} />
);
CardContent.displayName = 'CardContent';

const CardFooter = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => <div ref={ref} className={cn('flex items-center p-6 pt-0', className)} {...props} />
);
CardFooter.displayName = 'CardFooter';
```

`Badge` (cva, keep its existing `variant` union — read the current `badgeVariants` in the file and preserve the variant names), `Spinner` (`size = 'md'`), `Skeleton` (`variant = 'block'`), and `Divider` stay as in the current file, retinted only where they reference `void-*` surfaces → `border-border`/`muted`. Keep their existing prop shapes untouched so `token-usage-card.test.tsx` / `preset-picker.test.tsx` stay green.

- [ ] **Step 2: Verify**

Run: `cd frontend && bunx tsc --noEmit && bun test`
Expected: PASS (`token-usage-card.test.tsx`, `telegram-session-details.test.tsx` import from `card.tsx`).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/card.tsx
git commit -m "refactor(frontend): Card family onto shadcn tokens"
```

---

## Task 5: Input / Textarea / Label → shadcn

**Files:**
- Modify: `frontend/src/components/ui/input.tsx`

- [ ] **Step 1: Re-base on shadcn Input/Textarea/Label, keep export names `Input`, `Textarea`, `Label` and `InputProps`, `TextareaProps`**

```tsx
import * as React from 'react';
import { cn } from '@/lib/utils';

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {}

const Input = React.forwardRef<HTMLInputElement, InputProps>(({ className, type, ...props }, ref) => (
  <input
    type={type}
    ref={ref}
    className={cn(
      'flex h-9 w-full rounded-sm border border-border bg-background px-3 py-1 text-sm text-foreground',
      'font-mono placeholder:text-muted-foreground',
      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
      'disabled:cursor-not-allowed disabled:opacity-40',
      className
    )}
    {...props}
  />
));
Input.displayName = 'Input';

export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {}

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      'flex min-h-[80px] w-full rounded-sm border border-border bg-background px-3 py-2 text-sm text-foreground',
      'font-mono placeholder:text-muted-foreground',
      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
      'disabled:cursor-not-allowed disabled:opacity-40',
      className
    )}
    {...props}
  />
));
Textarea.displayName = 'Textarea';

const Label = React.forwardRef<HTMLLabelElement, React.LabelHTMLAttributes<HTMLLabelElement>>(
  ({ className, ...props }, ref) => (
    <label ref={ref} className={cn('text-sm font-medium font-mono uppercase tracking-wider text-muted-foreground', className)} {...props} />
  )
);
Label.displayName = 'Label';

export { Input, Textarea, Label };
```

- [ ] **Step 2: Verify**

Run: `cd frontend && bunx tsc --noEmit && bun test`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/input.tsx
git commit -m "refactor(frontend): Input/Textarea/Label onto shadcn tokens"
```

---

## Task 6: Modal / ConfirmDialog → radix Dialog

**Files:**
- Modify: `frontend/src/components/ui/modal.tsx`
- Test: `frontend/src/__tests__/modal-focus.test.tsx`

- [ ] **Step 1: Write/confirm the failing behaviour contract**

Run: `cd frontend && bun test modal-focus`
Expected: currently PASS against the hand-rolled modal. This test is the contract the radix port must satisfy (focus moves in on open, restores to trigger on close). Keep it green.

- [ ] **Step 2: Re-implement `Modal`/`ConfirmDialog` over radix `Dialog`, preserving the exact prop APIs**

Keep `ModalProps` (`isOpen, onClose, title?, description?, children, className?, size?: 'sm'|'md'|'lg'|'xl'`) and `ConfirmDialogProps` (`isOpen, onClose, onConfirm, title, description?, confirmLabel?, cancelLabel?, variant?: 'danger'|'default', isLoading?`). Use `Dialog`/`DialogPortal`/`DialogOverlay`/`DialogContent`/`DialogTitle`/`DialogDescription` from `@radix-ui/react-dialog` (installed in Task 1). Keep the panel `tabIndex={-1}` so the existing focus test's query finds a focusable panel; keep `aria-label="Закрыть"` on the close button and the `size`→`max-w-*` map.

```tsx
'use client';
import * as React from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from './button';

const modalSizes = { sm: 'max-w-sm', md: 'max-w-md', lg: 'max-w-lg', xl: 'max-w-2xl' } as const;

interface ModalProps {
  isOpen: boolean; onClose: () => void; title?: string; description?: string;
  children: React.ReactNode; className?: string; size?: 'sm' | 'md' | 'lg' | 'xl';
}

export function Modal({ isOpen, onClose, title, description, children, className, size = 'md' }: ModalProps) {
  return (
    <DialogPrimitive.Root open={isOpen} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-void-950/80 backdrop-blur-sm animate-fade-in" />
        <DialogPrimitive.Content
          className={cn(
            'fixed left-1/2 top-1/2 z-50 w-full -translate-x-1/2 -translate-y-1/2',
            'rounded-sm border border-border bg-card shadow-void-lg animate-slide-in-up',
            'focus:outline-none', modalSizes[size], className
          )}
        >
          <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-primary/50 to-transparent" />
          {(title || description) && (
            <div className="px-6 pt-6 pb-4 border-b border-border">
              {title && <DialogPrimitive.Title className="font-mono text-base font-semibold text-foreground uppercase tracking-wider">{title}</DialogPrimitive.Title>}
              {description && <DialogPrimitive.Description className="mt-1 text-sm text-muted-foreground font-mono">{description}</DialogPrimitive.Description>}
            </div>
          )}
          <div className="p-6">{children}</div>
          <DialogPrimitive.Close
            className="absolute top-4 right-4 h-7 w-7 flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors duration-150 font-mono text-lg"
            aria-label="Закрыть"
          >
            <X className="h-4 w-4" />
          </DialogPrimitive.Close>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
```

`ConfirmDialog` keeps its current body (the `Modal` + two `Button`s) unchanged except it now renders through the radix-backed `Modal` — keep `confirmLabel = 'Подтвердить'`, `cancelLabel = 'Отмена'`, `variant` mapping to `danger`/`default`.

- [ ] **Step 3: Verify the focus contract is intact**

Run: `cd frontend && bun test modal-focus`
Expected: PASS. If radix's focus placement differs from the test's expectation, set `Modal`'s panel focus via `onOpenAutoFocus` to focus the `DialogContent` (`tabIndex={-1}`) and confirm `onCloseAutoFocus` returns focus to the trigger.

- [ ] **Step 4: Verify dialog consumers**

Run: `cd frontend && bun test`
Expected: PASS, including `reset-context-dialog.test.tsx`, `preset-picker.test.tsx`, `media-content.test.tsx`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ui/modal.tsx
git commit -m "refactor(frontend): Modal/ConfirmDialog onto radix Dialog"
```

---

## Task 7: Toast → shadcn tokens (context API preserved)

**Files:**
- Modify: `frontend/src/components/ui/toast.tsx`

- [ ] **Step 1: Keep `useToast`/`ToastProvider` + `toasts`/`toast`/`dismiss`/`dismissAll` and `data-testid="toast-container"` exactly; restyle `ToastItem` on tokens**

The context, provider logic, max-5 cap, and auto-dismiss timers are already correct — leave them. Replace only the `variantStyles` map with token-based classes and keep `role="alert"`/`aria-live="assertive"`/`aria-label="Закрыть уведомление"`/`data-testid="toast-container"`:

```tsx
const variantStyles: Record<ToastVariant, string> = {
  success: 'border-success bg-success/10 text-success',
  error:   'border-destructive bg-destructive/10 text-destructive',
  warning: 'border-warning bg-warning/10 text-warning',
  info:    'border-primary bg-primary/10 text-primary',
};
```
Keep `variantIcons` and the `ToastItem`/`ToastContainer` structure unchanged (only class strings move to tokens: `bg-void-*` surfaces → `bg-card`/`border-border` where used). The `Toast`/`ToastVariant` types come from `@/types` (unchanged).

- [ ] **Step 2: Verify**

Run: `cd frontend && bunx tsc --noEmit && bun test`
Expected: PASS (`reset-context-dialog.test.tsx` mounts `ToastProvider` + `useToast`).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/toast.tsx
git commit -m "refactor(frontend): Toast visuals onto shadcn tokens (API preserved)"
```

---

## Task 8: Auth screens (login / register / reset-password / update-password)

**Files:**
- Modify: `frontend/src/app/(auth)/login/page.tsx`, `register/page.tsx`, `reset-password/page.tsx`, `update-password/page.tsx`

- [ ] **Step 1: Apply the Migration Pattern to the auth card (reference example)**

The auth screens share a centered card over the grid ground. Representative elevation (login page's form card) — this is the canonical shape the other three follow, each with its own fields/copy:

```tsx
<div className="min-h-screen flex items-center justify-center px-4">
  <Card className="w-full max-w-md border-border bg-card">
    <CardHeader>
      <CardTitle className="text-2xl font-display normal-case tracking-normal text-foreground">Вход в Mimic42</CardTitle>
      <p className="text-sm text-muted-foreground font-mono">Продолжите работу со своими агентами</p>
    </CardHeader>
    <CardContent className="space-y-4">
      {/* Input/Label per field; Button variant="default" full width */}
    </CardContent>
    <CardFooter className="justify-center">
      <p className="text-xs text-muted-foreground font-mono">Нет аккаунта? <a className="text-primary hover:underline" href="/register">Регистрация</a></p>
    </CardFooter>
  </Card>
</div>
```

Key edits per screen: `text-void-*`→ semantic tokens; the heading uses the Syne display face at `text-2xl` (elevate from mono-uppercase to a real display heading — this is the visible redesign win on the auth surface); field labels via `Label`; the submit button `variant="default" size="lg" isLoading={...}`; error text `text-destructive` with `aria-live="polite"`.

- [ ] **Step 2: Verify each screen renders and tests pass**

Run: `cd frontend && bunx tsc --noEmit && bun test && bun run build`
Expected: PASS; `next build` compiles the four routes.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/\(auth\)
git commit -m "feat(frontend): elevate auth screens onto shadcn primitives"
```

---

## Task 9: Layout (Header / Sidebar) + Dashboard

**Files:**
- Modify: `frontend/src/components/layout/Header.tsx`, `Sidebar.tsx`, `frontend/src/app/(dashboard)/layout.tsx`
- Modify: `frontend/src/app/(dashboard)/dashboard/page.tsx`, `frontend/src/components/agents/{AgentIdentity,AgentStatusBadge,AgentToggleButton}.tsx`

- [ ] **Step 1: Layout** — apply the Migration Pattern to the app shell. Sidebar nav items get `focus-visible` rings, active item `bg-accent text-accent-foreground` (was `void-*`); Header uses `text-foreground`/`text-muted-foreground`, `Button variant="ghost"` for icon controls with `aria-label`. Keep the desktop + mobile behaviours (mobile drawer) intact.

- [ ] **Step 2: Dashboard agent grid** — `Card` per agent on `bg-card border-border`; status via `AgentStatusBadge` recoloured to `success`/`warning`/`muted` tokens; `AgentToggleButton` keeps `Button`/`buttonVariants` API (tests: `agent-toggle-button.test.tsx`). Ensure the empty state (no agents) renders a real message + a `Button` CTA (Impeccable craft floor). Confirm 1..N agents lay out cleanly (grid `sm:grid-cols-2 lg:grid-cols-3`).

- [ ] **Step 3: Verify**

Run: `cd frontend && bunx tsc --noEmit && bun test && bun run build`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/layout frontend/src/components/agents frontend/src/app/\(dashboard\)/layout.tsx frontend/src/app/\(dashboard\)/dashboard
git commit -m "feat(frontend): elevate app shell and dashboard onto shadcn"
```

---

## Task 10: Agent page + tabs + sub-components

**Files:**
- Modify: `frontend/src/app/(dashboard)/agent/[id]/page.tsx`
- Modify: `frontend/src/components/activity/{TabActivity,TurnCard,ActionRow,ActivityDetails,MediaContent}.tsx`
- Modify: `frontend/src/components/agent/{TabAnalytics,TabSettings,TelegramSessionDetails,TokenUsageCard,FirstCommentSettings,PresetPicker,ResetContextDialog}.tsx`

- [ ] **Step 1: Agent header + tab switcher** — tabs as `Button variant="ghost"` / segmented control with `aria-selected`; active tab `text-primary border-b-2 border-primary`. Keep the raw agent-id removal already on `main`. Never render session strings/`api_hash` (they are not in the payload — assert no such field is shown in `TelegramSessionDetails`).

- [ ] **Step 2: Activity tab** — `TurnCard`/`ActionRow` on `bg-card border-border`; `Input` filter on tokens; `Spinner`/`Skeleton` loading + empty message; `MediaContent` keeps `Modal` (now radix) for previews (test: `media-content.test.tsx`).

- [ ] **Step 3: Analytics tab** — `TokenUsageCard` + charts (`recharts`) recoloured to the dark palette; `Skeleton` loading (test: `token-usage-card.test.tsx`). Ensure chart grid/text use `muted-foreground` for legibility on `bg-card`.

- [ ] **Step 4: Settings tab** — `Input`/`Textarea`/`Label` for name/`soul_prompt`/model; `PresetPicker` keeps its `Modal` + `Skeleton` (test: `preset-picker.test.tsx`); `ResetContextDialog` keeps `ConfirmDialog` + `useToast` (test: `reset-context-dialog.test.tsx`). `FirstCommentSettings`/`TelegramSessionDetails` on tokens.

- [ ] **Step 5: Verify**

Run: `cd frontend && bunx tsc --noEmit && bun test && bun run build`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/\(dashboard\)/agent frontend/src/components/activity frontend/src/components/agent
git commit -m "feat(frontend): elevate agent page and tabs onto shadcn"
```

---

## Task 11: Onboarding + Rebind

**Files:**
- Modify: `frontend/src/app/(dashboard)/onboarding/page.tsx`
- Modify: `frontend/src/app/(dashboard)/agent/[id]/rebind/page.tsx`, `frontend/src/components/agent/RebindPageClient.tsx`

- [ ] **Step 1: Onboarding** — `StepIndicator` recoloured to `primary`/`muted`; form steps use `Input`/`Textarea`/`Label`/`Button`; `ConfirmDialog` + `useToast` kept. Multi-step rhythm: `space-y-6` between step blocks. **Secrets:** the Telegram code/password fields must not echo secrets anywhere but their own inputs; no session string rendered.

- [ ] **Step 2: Rebind** — `RebindPageClient` uses `Card`/`Input`/`Button`/`Spinner`/`useToast` on tokens (test: `rebind-wizard.test.tsx`).

- [ ] **Step 3: Verify**

Run: `cd frontend && bunx tsc --noEmit && bun test && bun run build`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/\(dashboard\)/onboarding frontend/src/app/\(dashboard\)/agent/\[id\]/rebind frontend/src/components/agent/RebindPageClient.tsx
git commit -m "feat(frontend): elevate onboarding and rebind onto shadcn"
```

---

## Task 12: Global verification, DESIGN.md, design review

**Files:**
- Create: `docs/plans/DESIGN.md` (and `.impeccable/design.json` per the Impeccable documenter)

- [ ] **Step 1: Full frontend gate**

```bash
cd frontend && bunx tsc --noEmit && bun test && bun run build
```
Expected: all PASS, `next build` succeeds.

- [ ] **Step 2: e2e (Playwright)**

```bash
cd .. && uv run pytest -m e2e
```
Expected: PASS (the e2e suite drives the real frontend; it is the behavioural safety net). If an e2e test asserts on removed raw ids/labels, update the assertion to the new stable `data-testid`/role rather than reintroducing old markup.

- [ ] **Step 3: Impeccable mechanical detector over changed UI**

```bash
.impeccable/scripts/impeccable detect --json $(git diff --name-only origin/main...HEAD -- 'frontend/src/**/*.tsx')
```
Expected: no hard anti-pattern findings (generic gradient/glass where an asset belongs, many-vertex clip-paths, etc.). Fix mechanical findings; pass the rest to the reviewer.

- [ ] **Step 4: Screenshot round (desktop + mobile)**

Run the frontend, capture `desktop.png` (1440) and `mobile.png` (390) for the dashboard, agent page, and an auth screen. Critique against the direction (dark world preserved, hierarchy improved, shadcn consistency). One batched fix pass, one confirm pass — then stop.

- [ ] **Step 5: Finish review (Impeccable) + write DESIGN.md**

Spawn the `impeccable-finish-reviewer` with the request, PRODUCT.md, screenshots, and the direction summary; act on its disposition. Then run the Impeccable `document`/documenter to write `DESIGN.md` + `.impeccable/design.json` capturing the committed dark-world token system (the tokens from Task 2 are the source of truth).

- [ ] **Step 6: Commit**

```bash
git add docs/plans/DESIGN.md .impeccable
git commit -m "docs(frontend): record the shadcn dark-world design system"
```

---

## Task 13: Push + single Pull Request

- [ ] **Step 1: Push the branch**

```bash
git push -u origin shadcn-issue102
```

- [ ] **Step 2: Open ONE PR covering the whole redesign**

Use the GitHub MCP `create_pull_request` (check for a PR template first). Base `main`, head `shadcn-issue102`. Reference `Closes #102`. Summarise: shadcn adoption, token system, per-surface elevation, test/e2e evidence.

- [ ] **Step 3: Watch CI + PR health**

```bash
gh pr checks <PR#>
gh pr view <PR#> --json mergeable,mergeStateStatus,reviews
```
Expected: checks green, `mergeStateStatus: CLEAN`, `MERGEABLE`. Fix any failures (CI runs `tsc`/`bun test`/build). Move issue #102 on the project board to «На ревью» then «Сделано».

---

## Self-Review (already run by the planner)

- **Spec coverage:** issue #102 = (a) redesign via Impeccable → Tasks 8–12 (elevation + PRODUCT.md/DESIGN.md + review); (b) fully integrate Impeccable → done via `init`/PRODUCT.md and Task 12 detector+review+documenter; (c) migrate everything to shadcn → Tasks 1–7 (primitives) + 8–11 (every screen). Both segments (Task 9 grid for 1..N), dark-world preservation (Task 2 tokens), secrets-not-in-UI (Tasks 10–11) covered.
- **Placeholder scan:** no TBD/TODO/"add error handling"; every code step shows real code or an exact command; the only reused content is the "Migration Pattern" reference defined in this document (a documented pattern, not "similar to Task N").
- **Type consistency:** exports `Button`/`buttonVariants`, `Card`/`CardHeader`/`CardTitle`/`CardContent`/`CardFooter`/`Badge`/`Spinner`/`Skeleton`/`Divider`, `Input`/`Textarea`/`Label`, `Modal`/`ConfirmDialog`, `useToast`/`ToastProvider` are kept identical across Tasks 3–7, matching the existing call-site imports found in `frontend/src`.
