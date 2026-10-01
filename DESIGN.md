---
name: Mimic42
description: Dark terminal-world dashboard for AI Telegram agents — shadcn/ui over a void/plasma/neon/crimson palette.
colors:
  void-950: "#05050e"
  void-900: "#0a0a16"
  void-800: "#121220"
  void-700: "#1a1a28"
  void-600: "#252535"
  void-300: "#9090a0"
  void-100: "#e0e0e5"
  plasma-500: "#1a7fff"
  plasma-600: "#0062e6"
  plasma-300: "#70b8ff"
  neon-500: "#00e070"
  crimson-500: "#f43f5e"
  amber-500: "#f59e0b"
  background: "rgb(5 5 14)"
  foreground: "rgb(224 224 229)"
  card: "rgb(18 18 32)"
  primary: "rgb(26 127 255)"
  primary-foreground: "rgb(5 5 14)"
  muted: "rgb(26 26 40)"
  muted-foreground: "rgb(144 144 160)"
  border: "rgb(37 37 53)"
  ring: "rgb(26 127 255)"
  success: "rgb(0 224 112)"
  success-foreground: "rgb(5 5 14)"
  destructive: "rgb(244 63 94)"
  destructive-foreground: "rgb(5 5 14)"
  warning: "rgb(245 158 11)"
typography:
  display:
    fontFamily: "Syne, system-ui, sans-serif"
    fontWeight: 700
  body:
    fontFamily: "Syne, system-ui, sans-serif"
    fontWeight: 400
    fontSize: "0.9375rem"
    lineHeight: 1.6
  label:
    fontFamily: "'Space Mono', monospace"
    fontWeight: 400
    fontSize: "0.75rem"
    letterSpacing: "0.08em"
rounded:
  sm: "0.125rem"
  md: "0.1875rem"
  lg: "0.25rem"
spacing:
  sm: "8px"
  md: "16px"
  lg: "24px"
  panel: "3.25rem"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.lg}"
    height: "40px"
  button-destructive:
    backgroundColor: "{colors.destructive}"
    textColor: "{colors.destructive-foreground}"
    rounded: "{rounded.lg}"
    height: "40px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.foreground}"
    rounded: "{rounded.lg}"
    height: "40px"
  input:
    backgroundColor: "{colors.card}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.lg}"
    height: "40px"
  card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.lg}"
    padding: "24px"
---

# Design System: Mimic42

## Overview

**Creative North Star: "The Operator Terminal"**

Mimic42 is a control console for AI Telegram agents, so the interface behaves like
a piece of operator hardware: a near-black indigo ground with a faint blueprint grid,
sharp corners, monospace telemetry, and light that only appears when something means
something. shadcn/ui is the component vocabulary; its semantic tokens are mapped
*over* the void/plasma/neon/crimson palette, so the app reads as one dark world with
a component library inside it — never as a generic shadcn template and never as a
light theme.

Density is deliberate: quiet surfaces, hairline borders, color reserved for state and
action. Glow is a reward, not decoration — plasma for action/active, neon for
running/OK, crimson for destruction/failure, amber for idle/warning.

**Key Characteristics:**

- Dark ground, sharp corners (`radius: 0.25rem`), 40×40 blueprint grid + scan-line texture
- Syne for voice/headings, Space Mono for data/labels/IDs/timestamps
- Bright accent fills with dark (void-950) foregrounds — WCAG AA on every filled control
- Status color is semantic and exclusive: success / destructive / warning / muted
- Icons are `lucide-react` only; Telegram secrets never render

## Colors

The palette is a dark ground with three state accents and one action accent —
restrained ground, earned color.

### Primary
- **Plasma Blue** (`#1a7fff`): every action and active state — primary buttons, links,
  focus rings, active nav/tabs, glows on hover/selected surfaces.
- **Plasma Deep** (`#0062e6`): primary hover fill.

### Secondary
- **Neon Green** (`#00e070`): running/OK status, success badges and dots, positive deltas.
- **Crimson Rose** (`#f43f5e`): destructive actions, failed status, errors.
- **Amber** (`#f59e0b`): idle/warning status and caution badges.

### Neutral
- **Void 950** (`#05050e`): page ground and the foreground on bright fills.
- **Void 800 / 700 / 600** (`#121220` / `#1a1a28` / `#252535`): cards and rails, muted
  surfaces, inputs, borders.
- **Void 300 / 100** (`#9090a0` / `#e0e0e5`): secondary text, primary text.

### Named Rules
**The Dark Ground Rule.** No light surface, ever. New components take their ground from
`--background`/`--card`, never a hex of their own.
**The State-Only Rule.** `plasma/neon/crimson/amber` mean action or state. Decoration
borrows `border`, `muted`, and opacity — never an accent hue.

## Typography

**Display Font:** Syne (with `system-ui, sans-serif`)
**Body Font:** Syne (with `system-ui, sans-serif`)
**Label/Mono Font:** Space Mono (with `monospace`)

**Character:** The pairing is confident geometry against terminal telemetry — Syne
carries the product's voice, Space Mono carries everything a machine would print.

### Hierarchy
- **Display** (Syne 700–800, `text-2xl`/`clamp` on marketing): page titles, one `h1` per page state.
- **Headline** (Syne 600, `text-lg`): section and card headers (`CardTitle`, default `h3`).
- **Title** (Syne 500–600, `text-base`): item titles, modal titles.
- **Body** (Syne 400, `text-sm`, ~65–75ch max): descriptions, copy, chat text.
- **Label** (Space Mono 400, `text-xs`, uppercase, `tracking-wider`): field labels,
  column heads, timestamps, counts, IDs, chat handles.

### Named Rules
**The One H1 Rule.** Exactly one `h1` per rendered page state; use `CardTitle as="h1"`
for a page's main title rather than a second heading element.

## Layout

App shell: fixed left rail (nav, `w-68` at desktop) + main column with a sticky top bar;
dashboard and agent screens are card grids on a `2xl`/`3xl` breakpoint scale. Spacing
rhythm is Tailwind's 4px scale with named steps `13` (`3.25rem`), `18`, `22`, `68`
(`17rem`), `72`, `80`; `3xl: 1920px` for ultra-wide. Cards compose as
`CardHeader`/`CardContent`/`CardFooter` — when wrapping sub-components pass
`padding="none"` to avoid double `p-6`. Onboarding is a single narrow centered column;
auth is a centered panel. Density is compact-but-breathing: labels are small and quiet,
content lines are `text-sm`.

## Elevation & Depth

Hybrid: surfaces are flat at rest (separated by hairline `border` and one tonal step
from ground → card), and depth appears as state response — accent glows on interaction
and deep void shadows under overlays (modals, toasts).

### Shadow Vocabulary
- **Plasma hover** (`box-shadow: 0 0 10px rgba(26,127,255,0.2)`): active/selected cards, primary hover.
- **Neon live** (`box-shadow: 0 0 20px rgba(0,224,112,0.3)`): running status, success emphasis.
- **Crimson alert** (`box-shadow: 0 0 20px rgba(244,63,94,0.3)`): destructive hover, failed status.
- **Void lift** (`box-shadow: 0 4px 30px rgba(0,0,0,0.5)` / `0 8px 60px rgba(0,0,0,0.7)`): modal, toast, dropdown.

### Named Rules
**The Glow-Is-State Rule.** Glow appears only for interaction or status; at rest a
surface is flat and matte.

## Shapes

Corners are terminal-sharp: `--radius: 0.25rem` mapped to `rounded-lg`, with `md`/`sm`
below it. Borders are 1px hairlines in `--border` (`#252535`); always use the token
class `border-border`, never bare `border` as a color. Inputs and buttons share the same
radius and a `40px` control height so rows align. Status dots and badges are the only
pill/round shapes (`rounded-full` on dots, `rounded-sm` chips).

## Components

Primitives live in `frontend/src/components/ui/`, built on shadcn/radix with stable
app-facing APIs: `Button` (cva variants: `default | secondary | ghost | outline |
destructive | success | link`, plus `size`, `loading`), `Card` family
(`CardTitle`/`CardDescription`/`CardHeader`/`CardContent`/`CardFooter`, `variant`,
`padding`, `as`), `Input`/`Textarea`/`Label`, `Modal`/`ConfirmDialog` (radix Dialog),
`Toast` (context + `useToast`).

- **Button:** `focus-visible:ring-2 ring-ring ring-offset-2 ring-offset-background`,
  `disabled:opacity-40`, `active:scale-[0.97]`; filled variants use dark foreground on bright fill.
- **Card:** `bg-card border border-border rounded-lg`; `variant` switches in border/glow treatment.
- **Input:** `bg-card border-input focus-visible:ring-ring`; unique ids via `useId`.
- **Modal:** overlay `bg-black/70` + backdrop blur, panel `bg-card border-border shadow-void-lg`,
  Escape/overlay close, focus restore on close.
- **Toast:** bottom-right stack, `shadow-void-lg`, semantic left accent, `aria-live="polite"`.

## Do's and Don'ts

**Do** take ground, border, text, and status color from semantic tokens (`bg-card`,
`border-border`, `text-muted-foreground`, `text-success`/`text-destructive`).
**Do** keep one `h1` per page state and reserve Space Mono for machine-like text.

**Don't** introduce a light surface, a foreign hue, or emoji/unicode glyphs as controls
(use `lucide-react`).
**Don't** render Telegram secrets (`api_hash`, `phone_code_hash`, session strings) or
pad a `Card` that already wraps its own header/content sub-components.
