# Spec — Laundry Weather

*Status: approved 2026-08-22. This is the contract later reviews verify against.*

## Problem

There is a working "where should I hang the washing" model live in Home Assistant, built from
template sensors, `input_*` helpers and a 15-minute automation. It answers well, but two hard
limits of template helpers cap what it can ever become:

- **Template helpers cannot expose attributes.** The model computes an hourly forecast drying
  score internally, but has nowhere to put a series — so the dashboard can only ever show
  *now*, never a forward-looking drying chart.
- **Template helpers cannot call `weather.get_forecasts`.** The entire helper + automation
  two-layer workaround exists solely to route around this.

Two further gaps in the reference implementation:

- It scores exactly **one** indoor room. In practice two rooms are viable at once (8.26 vs
  8.50 hPa on the day of design), and picking between them is precisely the question.
- Every threshold is hard-coded in Jinja. The sun coefficient in particular is deliberately
  conservative and **untuned**; it needs to be adjustable against real washing loads without
  editing templates.

## What we are building

A HACS custom integration, domain `laundry_weather`, plus a bundled Lovelace card
`custom:laundry-weather-card`.

The integration scores every place washing could go — each configured indoor room, the line
under cover, and the same movable line pulled out into the sun — using a vapour-pressure-deficit
model, and derives when to move it out, when to bring it in, the best window, and whether dew
will re-wet it overnight. It exposes the hourly forecast score series as an attribute, which is
the thing the helper implementation could never do.

## Flow

**Setup.** A five-step UI config flow with explanatory copy at every step: name + weather
entity → outdoor sensors → sun/solar → rain detection → one indoor room, looping via an "add
another room" tick-box. Nothing is written to the user's system; every input is a
user-selected entity, so the integration works on any hardware.

**Running.** A coordinator polls the live sensors every 2 minutes and the hourly forecast every
15 minutes. Solar radiation is smoothed (a raw pyranometer reading swung 528 → 564 → 426 → 150
W/m² inside one afternoon; unsmoothed, the recommendation flaps). Everything derived is written
to entities, with the card's full payload riding on the recommendation sensor's attributes.

**Reading it.** One card. A headline that says whether today is worth it, a Klingon mascot
saying the same thing, a ranked table of spots, the timing block, and a forecast strip charting
the drying score forward for the next 24 hours.

**Tuning.** An options flow adjusts the sun coefficient, the outside-wins margin, the bring-in
floor, the band thresholds, and the display toggles — no template editing.

## The model

```
vpd_hpa(t, rh)      = 6.112 · e^(17.67t/(t+243.5)) · (1 − rh/100)        # Magnus
wind_norm(w)        = min(w_kmh, 20) / 20
indoor(t, rh)       = vpd(t, rh)                                         # still air
covered(vpd, wn)    = vpd · (0.55 + 0.45·wn)                             # roof kills the breeze
sky_fraction        = 0 if 1050·sin(elev) ≤ 20 else clamp(solar / (1050·sin(elev)), 0, 1)
sun_gate(elev)      = clamp((elev − 10) / 30, 0, 1)
live_sun_factor     = 1 + sun_coeff · sky_fraction · sun_gate            # sun_coeff default 1.2
open_line           = 0 if wet else vpd · (0.8 + 0.6·wn) · sun_factor
forecast_sun_factor = 1 + (sun_coeff/2) · min(uv, 5)/5
```

Bands: ≥12 Fast · ≥6 Moderate · ≥3 Slow · below that Barely. **Bands, not hours-to-dry** — an
hours figure is false precision until the model has been watched against real loads.

The Magnus formula was validated against the weather station's own `vapour_pressure_deficit`
reading and reproduced it exactly (3.42 vs 3.42 hPa).

## Acceptance criteria

**Model**

1. `vpd_hpa` reproduces the weather station's own VPD reading to 0.01 hPa across a table of
   captured `(temp, humidity, station VPD)` triples.
2. A recorded snapshot of the reference implementation's inputs replays through the new model
   and reproduces its recommendation, advice string and all four timings.
3. `bring_in_by` **always returns a time** and is computed with no reference to
   `move_outside_at` — enforced by the function signature taking no such argument, and by a
   named test where nothing ever beats indoors yet a real bring-in time still comes back.
   *(This is the bug that shipped in stage 1: gating bring-in on move-outside wiped the
   bring-in time exactly when washing was on the line and needed rescuing.)*
4. Outside must beat the best indoor room by 15% before it is recommended, so the answer does
   not flip-flop.
5. Two or more indoor rooms are scored, ranked, and the winner is named.
6. All hour-of-day logic is local-time correct under a non-UTC timezone.

**Integration**

7. The config flow completes with two rooms and produces the expected entity set.
8. Every field in every step has explanatory helper text; `strings.json` and
   `translations/en.json` are identical, so no field ever renders as a raw key.
9. The recommendation sensor exposes the hourly forecast series as
   `[{ts, hhmm, sun, cov, wet}, …]`, and the payload serialises under the recorder's 16 KB
   attribute limit.
10. A missing optional sensor degrades gracefully and is reported, rather than raising or
    silently scoring 0.
11. A weather provider with no UV index (Met.no) still produces a usable forecast sun factor
    via the cloud-cover fallback.
12. `manifest.json` version and every card `CARD_VERSION` match, checked by a test.

**Card**

13. The headline flips with conditions: *It Is a Good Day to Dry* / *It Is Not a Good Day to
    Dry*, driven server-side so headline and entity can never disagree.
14. The Klingon toggle swaps the headline and the mascot's speech bubble to
    `QaDmoHlu'meH QaQ jajvam` / `QaDmoHlu'meH QaQbe' jajvam`.
15. A mascot with a speech bubble, in **two states** — approving for a good drying day,
    scowling for a bad one — toggled from the card's visual editor, with config options to
    substitute your own images.
16. Status is conveyed by shape/fill **and words** — `●●●` Fast, `●●○` Moderate, `●○○` Slow,
    `○○○` Barely — never by colour. *(The owner is colour-blind: green/yellow/red/brown.)*
17. The forecast strip charts three series for the next 24 hours — line under cover, line in
    the sun, and the best indoor room as a flat reference — distinguished by dash pattern,
    marker shape and direct end labels, with no colour carrying meaning. Rain-likely hours are
    marked. Band thresholds appear as labelled reference lines.
18. Every card state renders correctly at desktop **and 380 px** with no horizontal scroll,
    evidenced by screenshots.
19. No raw entity IDs or jargon appear on any user-facing surface; copy leads with the band,
    not the hPa number.

**Docs**

20. The README explains the calculations and methods — what VPD is, the Magnus formula, why
    wind caps at 20 km/h, how the sun factor is derived and gated, why bands rather than hours,
    and how each timing is computed.
21. The README explains which companion integrations are worth having and what each buys you
    — local weather station, room environment sensors, sun, hourly forecast provider,
    statistics smoothing, rain detection — and what degrades if you lack them.
22. The Klingon strings are stated plainly as constructed, not canon.

## Non-goals

- **Not** an hours-to-dry estimate. Bands only, until the model has been watched against real
  loads.
- **Not** a replacement for the live production helpers in this release. Production migration
  is a separate decision, made after this has been proven on DEV/TEST.
- **Not** real Home Assistant internationalisation for Klingon. There is no `tlh` frontend
  locale; this is a boolean option that swaps a string.
- **Not** a notifier. No automations, no push notifications shipped in v1.0.0.
- **Not** a clothing-type model (towels vs shirts vs jeans). One score per location.
