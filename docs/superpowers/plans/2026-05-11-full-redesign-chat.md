# Full Redesign Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build three distinct UI experiences, response modes, rotating prompts, quick actions, and first-send reliability for Grebeshok Chat.

**Architecture:** Keep the existing FastAPI/SSE backend contract and React app shell. Add frontend configuration modules for design variants, response modes, prompt pools, and quick actions, then thread selected design/mode through `App` into focused components.

**Tech Stack:** React 18, TypeScript, Vite, TailwindCSS, FastAPI, SQLAlchemy, Fireworks SSE.

---

## File structure

- Modify `frontend/src/App.tsx`: app state, optimistic send reconciliation, design/mode wiring.
- Modify `frontend/src/components/EmptyState.tsx`: full redesign-specific empty states and rotating prompt cards.
- Modify `frontend/src/components/Composer.tsx`: design-specific composer and quick action chips.
- Modify `frontend/src/components/ChatView.tsx`: layout variants for message viewport.
- Modify `frontend/src/components/MessageBubble.tsx`: design-specific message presentation.
- Modify `frontend/src/components/Sidebar.tsx`: design-specific sidebar variants.
- Create `frontend/src/components/DesignPicker.tsx`: design selector.
- Create `frontend/src/components/ResponseModePicker.tsx`: response mode selector.
- Create `frontend/src/lib/personalization.ts`: design variants, response modes, quick actions, prompt pool.
- Modify `frontend/src/lib/api.ts`: allow `system_prompt` while streaming.
- Modify `frontend/src/lib/types.ts`: add frontend-only design/mode types.
- Modify `frontend/src/styles.css`: extra theme classes and animations.

## Tasks

### Task 1: First-send reliability

- [ ] Add optimistic user/assistant placeholder messages in `App.tsx` before calling `streamMessage`.
- [ ] Reconcile placeholders with `meta.user_message` and `meta.assistant_message_id`.
- [ ] Ensure `streamingId` is set before the first SSE delta.
- [ ] Verify first send on a new chat shows the user message immediately.

### Task 2: Response modes

- [ ] Add response mode definitions to `personalization.ts`.
- [ ] Add `ResponseModePicker.tsx`.
- [ ] Store selected mode in state and update chat `system_prompt` when changed.
- [ ] Send `system_prompt` when creating new chats.

### Task 3: Full redesign variants

- [ ] Add `DesignPicker.tsx`.
- [ ] Add design state in `App.tsx`.
- [ ] Implement `legacy`, `update2`, and `zeroSugar` branches in shell, sidebar, chat, empty state, composer, and messages.
- [ ] Add theme class hooks to `styles.css`.

### Task 4: Prompt rotation and delight features

- [ ] Add ~100 prompts to `personalization.ts`.
- [ ] Rotate four prompt cards in `EmptyState.tsx` on an interval.
- [ ] Add shuffle button.
- [ ] Add quick action chips in `Composer.tsx` that transform the draft.
- [ ] Add vibe/status widgets in the empty state/header area.

### Task 5: Verification

- [ ] Run `npm install` in `frontend/` if needed.
- [ ] Run `npm run lint`.
- [ ] Run `npm run typecheck`.
- [ ] Run `npm run build`.
- [ ] Fix failures without weakening checks.
