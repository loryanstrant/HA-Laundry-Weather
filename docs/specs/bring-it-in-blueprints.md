# Spec — "Bring it in" notification blueprints

*Status: approved 2026-08-22.*

## Problem

The integration knows when washing should come off the line. It says so on the card and in the
advice sentence — but only if you happen to be looking. Nobody watches a dashboard waiting for
rain.

The signal worth acting on is a *transition*: it has started raining, or drying has stopped, or
the deadline is close. Those moments are exactly when a phone in a pocket is more use than a
card on a wall.

## Constraints found before designing

**Home Assistant will not load a blueprint from a custom integration.**
`blueprint/models.py` resolves the folder as `hass.config.path("blueprints", domain)` — only
`config/blueprints/`. A blueprint shipped inside `custom_components/` is invisible. It has to
be imported by URL, which is the route HA supports and the one the owner's existing blueprints
already use.

**There is an established house pattern.** `blueprints/automation/loryanstrant/` already holds
`hydration_push_notification.yaml` and `hydration_tts_reminder.yaml` — separate push and TTS
files, each with a `source_url` pointing at its own GitHub path, prose descriptions, and
`selector:`-typed inputs. These match that shape.

One deliberate divergence: the hydration blueprints take **triggers as an input**, leaving the
user to build them. Here the triggers *are* the value — knowing rain has started is the whole
point — so they are built in and individually switchable.

## Flow

1. User imports one or both blueprints from the README.
2. They pick their Laundry Weather entities, a notify service or media player, and tick which
   alerts they want.
3. When a trigger fires **and the washing is actually out**, they get told, with the reason.

## Acceptance criteria

1. Two blueprints under `blueprints/automation/loryanstrant/`: one push, one TTS.
2. Both declare `domain: automation` and a `source_url` matching their own path in the repo.
3. Four independently switchable alerts:
   - rain has started
   - nothing is drying any more (`drying_now` turns false)
   - bring-in time approaching, by a configurable lead time defaulting to 30 minutes
   - dew will re-wet it overnight
4. **Every alert is gated on the washing being out.** No notifications about an empty line.
5. The `drying_now` alert uses a proper attribute state trigger, not a template.
6. Messages say *why*, not just "bring the washing in".
7. A flapping sensor cannot spam: `mode: single`, `max_exceeded: silent`.
8. Both parse as YAML, and Home Assistant accepts an automation created from each — a
   blueprint that fails validation is invisible rather than loud, so parsing is not enough.
9. The README shows how to import them, with working links.
10. Tests assert 2, and that each `source_url` matches its own filename — a copy-pasted
    `source_url` silently sends imports to the wrong file.

## Non-goals

- **Auto-installing into `config/blueprints/`.** HA does not support shipping blueprints from
  an integration, and writing into the user's config directory is more invasive than the
  Lovelace resource registration the card already does.
- **A "take it outside" blueprint.** Different question, can follow separately.
- **Shipping them in the HACS zip.** They live at the repo root, outside
  `custom_components/`, so the integration is unchanged and needs no version bump.
- Any change to the drying model or its thresholds.
