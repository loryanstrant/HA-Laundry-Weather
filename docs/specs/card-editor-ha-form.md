# Spec — Card editor on `ha-form`

*Status: approved 2026-08-23.*

## Problem

The card's visual editor is 137 lines of hand-built DOM producing browser-default controls. It
renders inside Home Assistant's own card-configuration dialog, surrounded by HA Material
fields, and does not look like any of them.

Two `standards/ux.md` rules are broken by it:

- **Consistency** — *"reuse the app's existing primitives before inventing new ones; a new
  control matches the treatment of its neighbours."* Raw `<select>` and
  `<input type="checkbox">` have different font metrics, focus rings and spacing from every
  other control in that dialog, and they follow the browser's `color-scheme` rather than the
  active Home Assistant theme.
- **Copy** — *"no raw identifiers where a name would do."* The sensor picker is a plain
  `<select>` listing `sensor.laundry_weather_recommendation`. That is a raw entity ID in the
  one field a non-developer has to get right, on a card where every other string was written
  specifically to avoid them.

There is also a structural point. v0.3.1 fixed a bug where the clock-format dropdown flashed
open and shut, because `set hass` re-rendered the whole subtree on every Home Assistant state
update and destroyed the `<select>` under the open popup. That fix is a *guard*: an equality
check before re-rendering. It is correct, and a later edit to `_render()` can undo it.

`ha-form` removes the possibility rather than guarding it. The sibling `ha-jokes` card has the
identical naive `set hass → _render()` shape and does **not** have the bug, because the form
element is created once and thereafter only `.hass`, `.schema` and `.data` are assigned; Lit
patches in place and there is no `innerHTML` to blow away.

## Scope

The **card** editor only — `laundry-weather-card-editor` inside
`custom_components/laundry_weather/www/laundry-weather-card.js`.

Not the integration's configuration screen. That is a Python config/options flow rendered by
Home Assistant itself, and it already uses `EntitySelector`, `BooleanSelector`,
`NumberSelector`, `SelectSelector` and `TextSelector`.

## Constraints found before designing

**This is not a new pattern for this fleet.** `ha-jokes`
(`custom_components/ha_jokes/www/ha-jokes-card.js`) is the in-house reference:
`EDITOR_SCHEMA` + `EDITOR_LABELS`, `computeLabel`, one `ha-form`, and a `value-changed`
listener that stops the inner event and re-emits `config-changed`.
`HA-Transformers-Allspark-UI/src/editor.js` does the same. Four other cards in the fleet
(hydration, oven, nav-menu-manager, component-monitor) are hand-built, and are being handled
in their own sessions.

**`ha-form` is only defined once Home Assistant loads its editor chunk.** `ha-jokes` uses a
bare `document.createElement("ha-form")` and gets away with it because the editor is only ever
built from the config dialog, which has already loaded that chunk. Mushroom's
`loadHaComponents()` — calling `hui-tile-card.getConfigElement()` to force the chunk — is the
community-canonical belt-and-braces, copied verbatim by `gauge-card-pro`.

**`customElements.whenDefined()` must not be called at module top level.** Home Assistant
replaces `window.customElements` with a scoped-registry polyfill while its core bundle boots,
so a top-level binding attaches to the native registry's method and may never fire. `ha-jokes`
documents this in a comment; the same trap applies here.

**`include_entities` exists on the entity selector** (`homeassistant/helpers/selector.py`,
`EntitySelectorConfig`), so the picker can keep today's exact candidate set — sensors carrying
a `spots` attribute — while gaining friendly names, icons and search. Filtering by integration
alone would offer all nine Laundry Weather sensors, most of which the card cannot read.

**`computeHelper` exists** (used 11× in Mushroom), so the two existing hint lines survive as
per-field helper text rather than being dropped.

## Flow

Unchanged for the user: *Edit card* → the same fields in the same order → changes apply live.
What changes is that the fields are Home Assistant's own, the sensor is chosen by name rather
than by entity ID, and the dropdowns open in an overlay layer instead of as native popups.

## Acceptance criteria

1. Every control is a Home Assistant component; no raw `<select>` or `<input>` survives in the
   editor.
2. The sensor picker offers exactly the entities the old `_candidates()` filter produced —
   sensors carrying a `spots` attribute — shown by friendly name, and searchable.
3. The two hint lines are still present, attached to their fields.
4. The Klingon control is a three-option dropdown (*Follow the integration setting* / *Always*
   / *Never*) and stores `null` / `true` / `false` respectively. A config written by the old
   checkbox editor loads into it unchanged.
5. Every other stored config key round-trips byte-identically; an existing dashboard needs no
   edit.
6. The `ha-form` element is the same node object across 20 consecutive `hass` assignments, and
   the editor still updates when the config genuinely changes.
7. `forecast_hours` keeps its 6–48 bounds.
8. Screenshots at desktop and ~380px show the editor matching the surrounding HA fields.

## Non-goals

- The card's rendering path. Only the editor changes.
- The integration's config/options flow.
- Migrating stored configs. Nothing about the stored shape changes, so there is nothing to
  migrate.
