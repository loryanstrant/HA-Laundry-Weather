# Decisions

Dated, non-obvious choices and the quirks that forced them. One entry per
decision, each ending in a lesson worth carrying elsewhere.

## 2026-08-22 — Why this exists at all

The reference implementation shipped as template sensors + `input_*` helpers +
a 15-minute automation, and works. It was rebuilt as an integration because two
template-helper limits are unfixable in helper-land:

- **Template helpers cannot expose attributes.** The model already computes an
  hourly forecast score internally; there was nowhere to put a series, so the
  dashboard could only ever show *now*.
- **Template helpers cannot call `weather.get_forecasts`.** The whole two-layer
  helper + automation workaround exists solely to route around this.

**Lesson:** when a template implementation grows a second layer purely to fetch
data or carry state, that is the signal it has outgrown templates.

## 2026-08-22 — `bring_in_by` is computed independently of `move_outside_at`

The reference implementation gated `bring_by` on `move_at` having found a slot.
When going outside stopped being worthwhile, the bring-in time was wiped along
with it — precisely when it mattered most, with washing already on the line.

Fixed here by construction rather than by care: `calc.bring_in_by()` takes no
`move_at` argument, so the coupling cannot be reintroduced without changing a
signature. A named test asserts a real bring-in time comes back from a series
where nothing ever beats indoors.

**Lesson:** when a bug is "two things were wrongly coupled", delete the
parameter. A signature that cannot express the bug beats a comment asking
people not to write it.

## 2026-08-22 — Solar radiation is smoothed inside the integration

Raw irradiance was observed swinging 528 → 564 → 426 → 150 W/m² within one
afternoon as cloud scudded over. `sky_fraction` is the noisiest term in the
model, and it multiplies the sun factor between 1.0 and 2.2 — so unsmoothed, the
recommendation flaps every few minutes.

The reference implementation solved this with a Statistics helper (30-minute
mean). Requiring a non-developer to build one before the integration works is a
setup footgun, so the integration applies its own 10-minute-time-constant EMA,
with an opt-out tick-box for people who already point at an averaged sensor.

**Lesson:** if the working configuration needs a helper built by hand first,
absorb the helper into the thing being configured.

## 2026-08-22 — One tunable moves both sun scales (D4)

The reference implementation used two different sun factors: live
`1 + 1.2·sky_fraction·gate` (max 2.2×, irradiance-driven) and forecast
`1 + 0.6·min(uv,5)/5` (max 1.6×, UV-driven). So `move_outside_at` and
`bring_in_by` were computed on a different scale from the score on screen, and
the forecast systematically under-promised relative to the live reading.

The forecast factor is now `1 + (sun_coeff/2)·min(uv,5)/5`. At the default
`sun_coeff = 1.2` this is bit-identical to the reference implementation — zero
behaviour change on day one — but raising the tunable no longer widens the gap
between the two scales. `diagnostics.sun_scale_ratio` reports the divergence so
it can be measured rather than guessed at.

**Lesson:** when two formulas must stay related, express one in terms of the
other's constant instead of writing the multiplied-out number twice.

## 2026-08-22 — Forecast sunshine falls back to cloud cover

UV index is the only sunshine signal in the reference forecast formula, and
Met.no's hourly forecast does not carry one. A Met.no user would get
`sun_factor == 1.0` for every hour forever, so `move_outside_at` would never
fire and the feature would silently do nothing.

`forecast_sun_model: auto` therefore picks `uv` when the hours carry it,
`cloud_coverage` × elevation gate when they don't, and a bare elevation gate as
a last resort. The card names the model in use when it isn't `uv`.

**Lesson:** a formula ported from one weather provider encodes that provider's
field list. Check which fields the *other* providers actually return before
calling the port faithful.

## 2026-08-22 — Bands, not hours-to-dry

The model reports Fast / Moderate / Slow / Barely, not "dry in 2.5 hours". The
underlying VPD figure is sound, but converting it to a time requires a
calibration constant per garment type, fabric weight and load size that nobody
has measured. An hours figure would look more useful and be less true.

**Lesson:** ship the precision you can defend. Revisit once there is a fortnight
of real loads to calibrate against.

## 2026-08-22 — The card carries no colour-coded state

The owner is colour-blind (green/yellow/red/brown). Drying bands are shown as a
fill meter plus the word — `●●●` Fast, `●●○` Moderate, `●○○` Slow, `○○○` Barely
— and the forecast strip distinguishes its three series by dash pattern, marker
shape and direct end-of-line labels. Nothing on the card encodes meaning in hue,
which also means it survives every theme.

**Lesson:** picking redundant channels up front is free; retrofitting them after
someone can't read the chart is not.

## 2026-08-22 — Klingon is a string swap, not internationalisation

Home Assistant's frontend has no `tlh` locale, so this is a boolean option that
swaps the card's headline and speech bubble. Entity states stay English in every
mode, so automations do not break when it is toggled.

The strings are **constructed, not canon**: `QaDmoHlu'meH QaQ jajvam` /
`QaDmoHlu'meH QaQbe' jajvam`, built from `QaD` "be dry" + `-moH` causative +
`-lu'` indefinite subject + `-meH` purpose + `-be'` negation, modelled on
*Heghlu'meH QaQ jajvam*. Not vetted by the Klingon Language Institute, and the
README says so.

**Lesson:** a joke in a second language still needs a sourcing note, or someone
will quote it as authoritative.
