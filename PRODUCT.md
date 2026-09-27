# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Two segments, both primary; the interface must scale from one agent to a fleet without breaking.

- **Individuals (likely Russian-speaking)** who want their own lifelike Telegram agent: they set its character, log in their Telegram account, and watch it act and converse.
- **Teams / small agencies** who manage several agents (sometimes for other people) and need to see many at once.

Tone stays lively and human, not enterprise-cold.

## Product Purpose

Mimic42 runs maximally realistic, human-like AI agents on real Telegram user accounts (a userbot via Telethon, not the Bot API). The dashboard is where a user configures an agent (character / SOUL.md, model, Telegram session) and then monitors and controls it. Success means the operator trusts the dashboard to show exactly what their agent is doing and to let them steer it — set up in minutes, legible while it runs.

## Positioning

Not a "bot" — a lifelike agent living on a real Telegram account, indistinguishable from a person, that the user fully owns and configures. The differentiator is the human quality of the agent combined with the depth of Telegram control (reactions, comments, media, first comments under posts), all managed from a multi-user web dashboard.

## Operating Context

The operator works in a web dashboard on desktop (mobile is already supported). They onboard an agent (phone → Telegram code → 2FA), set its personality and model, start/stop it, and monitor its activity feed, logs, analytics, and token usage. Agents act autonomously over long stretches; the operator checks in. Telegram login codes and session strings are secrets handled only by the backend.

## Capabilities and Constraints

- Multi-user; each user creates and manages their own agents.
- Agent = one Telethon user session + one LangChain agent; long-term memory via Mem0; short-term context from Postgres.
- Model chosen from a catalog via OpenRouter; structured replies come through tool calling.
- **Security constraint (must preserve):** `api_hash`, `phone_code_hash`, and the Telethon `StringSession` are backend secrets and must never reach the browser.
- Onboarding: Telegram phone → code (+ optional 2FA) → agent profile (name, `soul_prompt`, model).
- Controls: start / stop / rebind session / reset context / trigger message.
- Frontend: Next.js 14 + TypeScript + Tailwind, migrating to shadcn/ui components (issue #102).
- Open: full feature parity across every screen during the shadcn migration.

## Brand Commitments

- Name: **Mimic42**.
- Personality / voice: a maximally realistic, lively, human-like agent ("общается живо, как человек"). The product feels alive and personal, not corporate.
- **Dark aesthetic is a binding constraint.** The current dark "terminal" world — deep void background, electric-blue plasma accent, neon-green status, amber/crimson signals — is preserved and developed, not replaced. This redesign elevates and modernizes that dark world and moves it onto shadcn; it does not switch to a light theme or a different world. (The old look is still evidence to improve on, not a template to copy.)

## Evidence on Hand

- The full incumbent frontend and backend in this repo — the implementation is the evidence base.
- `README.md` and `AGENTS.md` document the product and its flows.
- The existing dark design system lives in `frontend/tailwind.config.ts` and `frontend/src/app/globals.css` (void / plasma / neon / crimson palettes; Syne + Space Mono fonts).
- No `DESIGN.md` and no `PRODUCT.md` existed before this record; no external logo or brand-asset file was found.

## Product Principles

1. The agent feels human — voice and presentation stay alive and personal.
2. Trustworthy monitoring — the operator always sees what the agent did and why.
3. Depth of Telegram control — expose real capability, not a toy subset.
4. Scales one to many — the same interface works for a single agent or a fleet.
5. Secrets never reach the browser — security is part of the product truth.
