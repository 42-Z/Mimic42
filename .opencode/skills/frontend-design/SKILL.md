---
name: frontend-design
description: Use ONLY when working with the Mimic42 frontend UI, CSS, Tailwind classes, component styling, responsive design, or the project's dark cyberpunk design system. Covers color tokens (void, plasma, neon, crimson), typography (font-mono, font-display), glass cards, spacing, and mobile breakpoints.
---

# Frontend Design System — Mimic42

## Color Palette

| Token | Usage | Hex Approx |
|-------|-------|------------|
| `void-950` | Page background | `#05050e` |
| `void-900` | Card bg, sidebar | `#0a0a1a` |
| `void-800` | Hover states, inputs | `#111122` |
| `void-700` | Borders | `#1a1a2e` |
| `void-600` | Muted text | `#333344` |
| `void-500` | Secondary text | `#555566` |
| `void-400` | Body text | `#777788` |
| `void-300` | Primary text | `#aaaabb` |
| `void-100` | Headings | `#ccccdd` |
| `plasma-400` | Accent (logo, active) | `#00d4ff` |
| `plasma-500` | Pulse indicators | `#00b8e6` |
| `neon-400` | Success, online | `#00ff88` |
| `neon-600` | Success muted | `#00cc6a` |
| `crimson-400` | Error, danger | `#ff3366` |
| `crimson-500` | Error hover | `#cc2952` |
| `amber-400` | Warning | `#ffaa00` |

## Typography

- **font-mono**: All UI text, buttons, labels, tabs (`font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace`)
- **font-display**: Page headings only
- **font-size scale**:
  - `text-[10px]`: timestamps, badges, status indicators
  - `text-xs`: labels, tab text, KPI values
  - `text-sm`: card titles, agent names, buttons
  - `text-xl`: page headings (`font-display`)
  - `text-3xl`: large KPI numbers

## Components

### Card
```tsx
<Card variant="glass" padding="md" className="border border-void-700">
```
- `variant="glass"`: `bg-void-900/60 backdrop-blur-sm border border-void-700/60`
- `padding="none"` for scrollable containers (logs, feed)
- `padding="md"` for content cards

### Button
- **variant="success"**: green start actions
- **variant="danger"**: red stop/delete actions
- **variant="outline"**: secondary actions
- **variant="ghost"**: navigation, low emphasis
- **size="sm"**: almost all buttons
- Always include `leftIcon` for clarity

### Input
```tsx
<Input className="bg-void-800 border-void-600 focus:border-plasma-600" />
```

## Responsive Breakpoints

| Name | Width | Usage |
|------|-------|-------|
| mobile (default) | < 640px | Stack layouts, hide secondary elements |
| `sm:` | ≥ 640px | Show hidden desktop elements |
| `md:` | ≥ 768px | Sidebar always visible, 2-col layouts |
| `lg:` | ≥ 1024px | 3-col dashboard, expanded sidebar |

### Mobile-first rules
- Default = mobile layout
- Use `sm:`, `md:`, `lg:` to enhance for larger screens
- Never use `max-width` media queries with Tailwind

### Common mobile patterns
```tsx
// Hide on mobile, show on desktop
<div className="hidden sm:block">...</div>

// Show only on mobile
<div className="md:hidden">...</div>

// Stack on mobile, row on desktop
<div className="flex flex-col sm:flex-row">...</div>

// Full width on mobile, constrained on desktop
<div className="w-full sm:max-w-xs">...</div>
```

## Spacing

- Use `space-y-4`, `space-y-6` for vertical rhythm
- Use `gap-4`, `gap-6` for grid/flex gaps
- Use `p-2` for compact inner spacing (log rows)
- Use `p-6` for page padding
- Use `px-3 py-2` for nav items

## Animation

- `animate-fade-in`: page entrance
- `animate-pulse`: live indicators
- `animate-status-pulse`: running agent dot
- `transition-all duration-150`: interactive elements

## Rules

1. Never use arbitrary values without a design reason (`w-[123px]`)
2. Always use `rounded-sm` (2px) — no large rounded corners in this UI
3. Border colors should always match the background tier (void-700 on void-900)
4. Text hierarchy: void-500 (meta) → void-300 (body) → void-100 (headings)
5. Accent colors (plasma, neon, crimson) are for status and CTAs only
