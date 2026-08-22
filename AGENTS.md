# AGENTS.md — HA-Laundry-Weather

> Cross-tool agent instructions (Claude Code, Copilot agent mode).
> **Gotcha:** Copilot *inline* suggestions do NOT read this file — any rule that
> must hold for inline completions is mirrored into
> `.github/copilot-instructions.md`. Keep the two in sync.

## Project

Home Assistant custom component `laundry_weather` — scores where to hang washing
(indoor rooms, the line under cover, the same line out in the sun) from a
vapour-pressure-deficit model, and ships a bundled Lovelace card
`custom:laundry-weather-card`.

Canonical repo on SOUNDWAVE/Gitea; GitHub is a one-way push mirror and the front
door for external issues/PRs. **Never merge PRs or create tags on GitHub** — the
mirror runs in prune mode every 8h and force-deletes GitHub-only refs.

The approved contract is `docs/specs/laundry-weather.md`. Changes to behaviour
update the spec in the same commit.

## How to work here

- Use the `plan-before-coding`, `write-a-test-plan`, and `build-ha-component`
  skills (global, in `~/.copilot/skills/` — also available to Claude Code).
- Smallest shippable slice; one thing at a time.
- No new tools unless they replace something.
- At end of task, capture any reusable lesson into `DECISIONS.md` here, or into
  `dev-standards/DECISIONS.md` if it generalises beyond this repo.

## Repo shape

- `custom_components/laundry_weather/calc.py` is the whole drying model and
  **must never import Home Assistant**. That is what makes it testable without a
  running instance, and it is where nearly all the tests live.
- `coordinator.py` does all the I/O — state reads, unit normalisation, solar
  smoothing, forecast fetching — and hands plain numbers to `calc`.
- `www/*.js` is part of the integration's frontend, shipped inside the component
  zip. It is not a separate HACS plugin.

## Build / test / deploy

See `build-ha-component`. Short version: `hassfest` + HACS validate + `pytest`
is the gate; deploy by copying the **published release** into
`custom_components/laundry_weather` with backup + auto-rollback; smoke-test the
config flow via the HA API. Verify the served response body, not HTTP 200.

`manifest.json` version and every card `CARD_VERSION` are bumped together to the
same value on every release, even for untouched cards. `test_packaging.py`
enforces this.

## Accessibility

The owner is colour-blind (green/yellow/red/brown). Card status is conveyed by
shape/fill **and words** — `●●●` Fast, `●●○` Moderate, `●○○` Slow, `○○○` Barely
— never by colour. Chart series are distinguished by dash pattern, marker shape
and direct labels, never by hue.

## Secrets

HA tokens and deploy keys live in Gitea Actions secrets — never in the repo.
