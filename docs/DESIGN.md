# Design

How DevPilot should look, and why. The goal is a calm engineering tool that reads like it was
designed on purpose: flat, dense, quiet, and honest about what is verified.

Design file (Figma): <https://www.figma.com/design/m3furE0hl3ufuNAHWvJJ3I>

## Rules

1. **No decoration.** No gradients, glow, blur, glass effects or decorative shadows. A surface is a
   flat fill with a 1px border.
2. **Color means status.** Green is passed or verified, amber is needs a look, red is failed or
   critical. Nothing else is colored. There is no accent hue: the primary color is "ink" (near-white
   on dark, near-black on light). Charts use ink and grays.
3. **Tables and lists, not card grids.** Repeating data is a table with hairline row dividers. A set
   of key numbers is one bordered strip with dividers, not four separate cards.
4. **Small, consistent radii.** 3px for tags, 4px for controls, 6px for panels. Nothing is pill-shaped.
5. **Two typefaces.** IBM Plex Sans for interface text, IBM Plex Mono for anything a developer
   might copy: file paths, line numbers, commit hashes, request ids, counts and code.
6. **Text-only navigation.** The active page is a filled row with a heavier weight, not an icon or a
   color.
7. **Plain language.** Sentence case, ordinary verbs ("Request a review"), no sparkle icons and no
   "AI-powered" copy.
8. **Say what is verified.** AI output shows whether it was checked: a green *Verified* tag where
   quoted code or log lines were matched against the real source, a neutral *Hypothesis* tag where it
   is a guess.

## Tokens

The CSS custom properties in `apps/web/app/globals.css` are the source of truth. The Figma
collections **Color** (dark) and **Color (Light)** mirror `:root` and `.light` one for one, and each
Figma variable has its CSS name as code syntax.

| Token | Dark | Light | Use |
|---|---|---|---|
| `background` | `#101113` | `#F6F6F4` | page |
| `sidebar` | `#0C0D0F` | `#EEEEEB` | sidebar |
| `card` | `#15171A` | `#FFFFFF` | panels |
| `elevated`, `muted` | `#1C1F23` | `#F0F0ED` | table headers, hovered rows, inputs |
| `foreground` | `#ECEEF0` | `#17181A` | text |
| `muted-foreground` | `#9BA2AB` | `#5A5F66` | secondary text |
| `border` | `#2A2E34` | `#DDDDD8` | hairlines |
| `border-strong` | `#666D76` | `#85857F` | form field and outlined button borders (3:1 or better on every surface) |
| `primary` | `#ECEEF0` | `#17181A` | primary button, links |
| `primary-foreground` | `#101113` | `#FFFFFF` | text on primary |
| `success` | `#4FB477` | `#1F7A4A` | passed, verified |
| `warning` | `#D9A441` | `#8F5F0A` | needs a look |
| `danger` | `#E5645C` | `#B3261E` | failed, critical, destructive |
| `chart-3` | `#666D76` | `#85857F` | third chart series |

Status tags use the status color at about 15% as the fill (`bg-success/15` in Tailwind; the Figma
variables `success-muted`, `warning-muted` and `danger-muted`) with the full color as text.

Spacing is a 4px grid. Type scale (Plex Sans unless noted): page title 24/32 semibold, section
title 16/24, body 14/22, interface text 13/20 (the default), label 12/16 medium, caption 12/16,
code 12/18 and 13/20 (Plex Mono), figures 24/32 medium (Plex Mono).

Contrast was computed, not eyeballed. Text on its usual surfaces passes AA (4.5:1) in both themes,
with one exception: danger text on its 15% tint in the dark theme is 4.47:1, so a red tag in dark
mode should use a 12% tint or a slightly lighter red. Borders that identify a control (form fields,
outlined buttons) need 3:1, and `border-strong` now meets it; the plain `border` hairline is
decoration between rows and does not. **Known gap:** the form fields in the app still use the hairline
`border` and should move to `border-strong`, ideally through one shared Input component. Focus rings
use the primary color, so they show on both themes.

## State of the design

| Part | Status |
|---|---|
| Foundations page (palettes, type, spacing, radius) | done in Figma. Its `border-strong` (`#3B4148`, `#C4C3BC`) and dark danger tint are the values before the contrast fix above and need updating |
| Components: Button (8 variants), Tag (4), Nav item (2) | done in Figma |
| Dashboard screen | done in Figma, checked by eye |
| Repositories and Team (with audit log) screens | built in Figma after a layout fix; **not re-checked by eye** |
| Code review detail, CI analysis, Assistant, Code search, Analytics, Integrations, Settings, Login, landing page | **not designed yet** |
| Light-theme screens | not drawn (the Starter plan allows one mode per variable collection, so Light is a separate collection and the screens are dark only) |
| Code | **tokens, fonts and chart colors only.** The page layouts (summary strip, tables, panels) are not yet changed to match the Figma screens, and the result has not been looked at in a browser |

## Applying a screen to code

Work one screen at a time: compare the Figma screen with the component, change layout and classes
to match, keep behavior and tests, then check it in the browser in both themes. Components that
should be shared (Button, Tag, nav item, panel, table) live in `apps/web/components/ui/`.
