# Copilot instructions — HA-Laundry-Weather

> Canonical copy lives in `dev-standards/templates/ha/`. Edit there, then sync.
> This file is read by Copilot chat **and** inline suggestions, so critical
> rules live here (mirrored from `AGENTS.md`, which inline ignores).

## What this repo is

A Home Assistant custom component named `laundry_weather` that scores where to
hang washing, plus a bundled Lovelace card `custom:laundry-weather-card`.

## Working style

- Plan before non-trivial changes; ship the smallest useful slice.
- Don't introduce a new tool/dependency unless it replaces something.
- Keep responses concise.

## HA component rules

- `manifest.json` version is bumped on every release (HACS reads it); `domain`
  matches the `custom_components/laundry_weather/` folder; deps pinned in
  `requirements`.
- **Every card's `CARD_VERSION` is bumped to the same value as
  `manifest.json` on every release**, even untouched cards.
- Prefer config flow over YAML. Ship `translations/en.json` as a copy of
  `strings.json` — without it, option fields render as raw keys.
- Releases are auto-cut by CI on tag/merge — don't hand-cut.

## Repo rules

- `calc.py` must never import Home Assistant. It is the drying model, and it is
  testable precisely because it has no HA dependency. I/O belongs in
  `coordinator.py`.
- `bring_in_by` is computed with **no reference to** `move_outside_at`. Coupling
  them wiped the bring-in time exactly when washing was on the line. The
  function signature takes no `move_at` argument; keep it that way.
- Report drying **bands**, never hours-to-dry.

## Accessibility (hard rule)

The owner is colour-blind (green/yellow/red/brown). Never encode status,
severity or a chart series in colour alone. Use fill glyphs plus the word
(`●●○` Moderate), and distinguish chart lines by dash pattern and marker shape.

## Test & deploy

- Gate = `hassfest` + HACS validation + `pytest`
  (`pytest-homeassistant-custom-component`). No live instance needed.
- Deploy = install the **published release zip** into
  `custom_components/laundry_weather` + restart HA. Back up outside
  `custom_components/`; auto-rollback on failed smoke test.
- Do **not** drive the HACS UI to test — file-copy simulates the post-install
  state and is far more reliable.

## Never

- Commit HA long-lived tokens or deploy keys. They live in Gitea Actions secrets.
- Merge a PR or create a release tag on GitHub. Gitea is canonical.
