# Full Redesign Chat Design

## Goal

Build three genuinely different chat UI experiences, fix first-send reliability,
add response modes, rotate the four central quick-prompt cards from a large pool,
and add small delight features that make the personal AI chat feel more capable.

## Approved direction

The user explicitly rejected a color-only theme switch. The design selector must
change layout, visual language, component shapes, controls, and information
architecture.

## Experiences

### Legacy

Keeps the current product shape: left sidebar, top header, model picker, central
empty state, bottom composer. This is the safe familiar baseline.

### Update 2.0

A modern, bright, high-energy redesign:

- Gradient/cyber-pop background with animated glow layers.
- Floating rounded sidebar rather than a full-height flat rail.
- Command-bar style top area with model, mode, design, shuffle, and activity
  chips.
- Dashboard-like empty state with large hero card, rotating prompt grid, mini
  widgets, and quick-action buttons.
- Composer as a floating glass command dock.

### Zero Sugar

A radically minimal terminal/notebook redesign:

- Monochrome visual language.
- Flat split-panel layout.
- Compact dense controls.
- Messages in document-like blocks.
- Composer as a terse command input area.

## Response modes

Add selectable answer modes that map to system prompts:

- Обычный
- Кодер
- Учитель
- Злой ревьюер
- Креативщик
- Кратко
- Исследователь

The selected mode should be stored in the current chat as `system_prompt` and
used for new chats. The UI displays mode metadata as chips/cards.

## First-send bug

When sending in a new or existing chat, the UI should immediately append a local
user message and assistant placeholder before the SSE `meta` event. When `meta`
arrives, reconcile those optimistic messages with server IDs instead of adding
duplicates. This makes the first click feel accepted and prevents the user from
needing to send again.

## Rotating prompt cards

Replace the fixed four cards with a large prompt pool of about 100 short prompts.
Show four cards at a time. Rotate automatically every few seconds while the empty
state is visible. Include a shuffle control.

## Extra features

Add three small interaction features:

1. Quick action chips that transform the draft: improve, shorten, translate,
   add structure, make it funnier.
2. A visible session vibe/status area that reflects selected design and mode.
3. Random prompt shuffle button.

## Scope constraints

- Do not add new external UI dependencies.
- Keep all Fireworks API access server-side.
- Maintain existing chat persistence and streaming contract.
- Preserve `Legacy` as a familiar fallback.
