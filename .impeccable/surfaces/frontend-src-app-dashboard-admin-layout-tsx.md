---
version: 1
slug: "frontend-src-app-dashboard-admin-layout-tsx"
primary_target: "frontend/src/app/(dashboard)/admin/layout.tsx"
related_targets: []
---

# Admin dashboard shell

Scope: the `/admin` route family and its navigation inside the existing authenticated dashboard. Mode: Operate.

Audience: platform administrators who need to move between statistics, user records, prompt presets, and shared Telegram application settings. The shell must not depend on the administrator owning an agent.

## Direction contract

THESIS: one verified admin boundary gives platform operations a clear place without confusing them with per-agent controls.

OWN-WORLD: inherit the current dark Operator Terminal: void surfaces, plasma for active navigation and actions, semantic status colors, Syne content text, Space Mono telemetry, and the existing sharp-radius component language.

STORY: retain the current dashboard shell; once `/me` confirms the role, expose the admin section and its four deep-linked destinations. While access is being checked, failed, or denied, protected children stay unmounted.

FIRST VIEWPORT: existing Sidebar and Header remain the outer frame. The admin content starts with a compact title and four-link subnavigation, followed directly by each page's working content; the shell does not wrap the whole page in a decorative card.

FORM: a local extension of the established dashboard, not a new visual world. No concept-seed round is needed for this tightly scoped shell; the approved product plan pins the existing style and the four destinations.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

Constraints: backend role checks remain authoritative; middleware still authenticates all routes; `/admin` bypasses only the “must own an agent” redirect. Regular navigation and onboarding remain unchanged. Keep the shell responsive and use existing components before adding primitives.

Unresolved decisions: none for the shell; page content and its states are defined in the later implementation stages.
