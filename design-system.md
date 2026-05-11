# Grebeshok Chat — Design System

Project context: personal AI chat web app powered by the Fireworks API.
Visual direction: dark-first, calm, focused. Inspired by modern AI chat
products (Claude, ChatGPT, Perplexity) but with a warmer, slightly more
personal feel.

## Tokens

### Colors

Defined as CSS custom properties in `frontend/src/styles.css` and
mirrored in `tailwind.config.ts` as semantic colors.

Surface (dark theme, default):

| Token            | Value       | Usage                                          |
| ---------------- | ----------- | ---------------------------------------------- |
| `--bg`           | `#0b0b0f`   | App background                                 |
| `--surface-1`    | `#111118`   | Sidebar, raised surface                        |
| `--surface-2`    | `#16161f`   | Cards, code blocks, assistant message bubble   |
| `--surface-3`    | `#1d1d28`   | Hover, focus background                        |
| `--border`       | `#262633`   | Default border                                 |
| `--border-muted` | `#1c1c26`   | Subtle dividers                                |

Text:

| Token             | Value       | Usage                  |
| ----------------- | ----------- | ---------------------- |
| `--text`          | `#e8e8ef`   | Primary text           |
| `--text-muted`    | `#9c9cae`   | Secondary text         |
| `--text-subtle`   | `#646476`   | Tertiary / placeholder |

Accent (brand):

| Token             | Value       | Usage                  |
| ----------------- | ----------- | ---------------------- |
| `--accent`        | `#7c5cff`   | Primary action, focus  |
| `--accent-hover`  | `#8b6dff`   | Hover state            |
| `--accent-soft`   | `#7c5cff22` | Soft tinted backgrounds|

Semantic:

| Token         | Value     |
| ------------- | --------- |
| `--success`   | `#3ddc97` |
| `--warning`   | `#ffb454` |
| `--danger`    | `#ff6b6b` |

### Typography

- Font: `Inter` (UI) and `JetBrains Mono` (code), loaded via Google Fonts.
- Scale (Tailwind-equivalent):
  - `text-xs` 12px — meta, timestamps
  - `text-sm` 14px — UI, buttons
  - `text-base` 15px — chat body (chat lines are slightly larger than UI chrome)
  - `text-lg` 17px — section headings
  - `text-xl` 20px — page titles
- Line height: `leading-relaxed` (1.625) on chat bubbles, `leading-snug`
  (1.375) on UI chrome.

### Spacing

Use the Tailwind 4-px scale. Allowed values: `0.5, 1, 1.5, 2, 2.5, 3, 4,
5, 6, 8, 10, 12`. Avoid arbitrary `px-[13px]`-style values.

### Radius

- `rounded-md` 6px — buttons, inputs
- `rounded-lg` 10px — cards, message bubbles
- `rounded-xl` 14px — modal, large cards
- `rounded-full` — avatars, pill chips

### Shadow

- Default raised: `shadow-[0_4px_24px_-8px_rgba(0,0,0,0.6)]`
- Floating popover: `shadow-[0_12px_40px_-12px_rgba(0,0,0,0.7)]`

### Motion

- Hover transitions: `transition-colors duration-150`
- Element entrance: `transition-all duration-200 ease-out`
- Stream cursor: blink 1s steps(2, start) infinite

## Components

### Message bubble

- User: right-aligned, `bg-accent-soft` background, `text` color.
- Assistant: left-aligned, `bg-surface-2`, white text. Reasoning chain
  rendered in a collapsible card above the answer with `text-text-muted`.

### Sidebar

- Width: `w-72` on `md+`. Collapsible to icon-only on mobile via overlay.
- Chat row: `px-3 py-2 rounded-md` with `hover:bg-surface-3` and active
  state `bg-surface-3`.

### Composer

- Multiline `textarea` with autosize, max-height `40vh`.
- Send button: square, accent background, disabled when empty.
- Hotkey: Enter sends, Shift+Enter inserts newline.

## Rules

- Every interactive element must have a visible `:focus-visible` ring
  using `ring-2 ring-accent ring-offset-0 ring-offset-bg`.
- All icons from `lucide-react`, sized `w-4 h-4` or `w-5 h-5`.
- No arbitrary one-off colors. If a color does not exist in this file,
  add it here first.
