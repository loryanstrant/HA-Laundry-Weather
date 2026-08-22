# The drying model

The full derivation, including where each constant came from and how confident it is worth
being about it. The README carries the readable version; this is the working.

The whole model lives in `custom_components/laundry_weather/calc.py`, which deliberately
imports no Home Assistant — that is what makes it testable without a running instance, and
nearly all of this repository's tests exercise it directly.

---

## 1. Why vapour pressure deficit

Evaporation from wet fabric is driven by the difference between the vapour pressure at the wet
surface and the vapour pressure of the surrounding air. Saturated air cannot take any more
water however warm it is; bone-dry air pulls hard even when cold.

**Vapour pressure deficit** is exactly that difference, assuming the fabric surface is
saturated — which it is, while it is still wet:

```
vpd = e_s(T) − e_a          where e_a = e_s(T) × rh/100
    = e_s(T) × (1 − rh/100)
```

Saturation vapour pressure `e_s` comes from the Magnus approximation, in hPa:

```
e_s(T) = 6.112 × exp(17.67·T / (T + 243.5))
```

Valid roughly −40 °C to +50 °C, which comfortably covers anywhere you would hang washing.

### Confidence

Checked against an Ecowitt weather station that computes its own vapour pressure deficit in
firmware, using a simultaneous reading:

| | Value |
|---|---|
| Temperature | 13.1 °C |
| Relative humidity | 66% |
| Station's own VPD | 5.11344684691491 hPa |
| Magnus, as implemented | 5.121959813350014 hPa |
| **Difference** | **0.0085 hPa** (0.17%) |

The narrowest gap between two drying bands is 3 hPa, so the residual is roughly 350 times
smaller than the smallest thing it could affect. It cannot change an answer.

Worth stating plainly because the earlier design notes claimed the formula reproduced the
station *exactly* (3.42 vs 3.42): that was a match at two decimal places, not a match. The
conclusion survives; the wording did not, and `tests/test_calc_vpd.py` now asserts the real
tolerance rather than a match that does not exist.

### The consequence people find surprising

Because `e_s` rises steeply with temperature but humidity scales the whole thing linearly,
cold dry air routinely beats warm humid air:

| Conditions | VPD | Band |
|---|---|---|
| 10 °C, 30% rh | 8.6 hPa | Moderate |
| 25 °C, 85% rh | 4.8 hPa | Slow |

A crisp winter morning genuinely dries washing faster than a muggy summer afternoon, and the
card says so.

---

## 2. Wind

Moving air strips away the saturated boundary layer that forms against wet fabric. The benefit
is strongly diminishing: most of it arrives in the first few km/h, and past roughly 20 km/h
extra wind adds little while starting to cost pegs.

So wind is normalised against that ceiling and used as a 0–1 multiplier:

```
wn = min(wind_kmh, 20) / 20
```

Applied differently by position:

| Position | Ventilation factor | At `wn=0` | At `wn=1` |
|---|---|---|---|
| Indoor room | *none* | 1.00 | 1.00 |
| Line under cover | `0.55 + 0.45·wn` | 0.55 | 1.00 |
| Line in the sun | `0.8 + 0.6·wn` | 0.80 | 1.40 |

Indoor air is treated as still — no wind term at all — which is why a warm dry sunroom
regularly beats a breezy overcast line.

The covered line is penalised in still air because a roof also blocks air movement, and it
tops out at parity with open air because a sheltered line in a good breeze does fine. The open
line can exceed 1.0 because full exposure genuinely beats the reference case.

**Confidence: low-to-moderate.** These coefficients are physically reasonable and produce
sensible rankings, but they are not measured. They are shaped so the *ordering* is right,
which is what the card actually reports.

---

## 3. Sun

Direct sun warms the fabric above air temperature, raising the vapour pressure at the surface
well beyond what the air temperature suggests. It is the largest single effect available
outdoors, and the hardest to measure honestly.

### Separating cloud from time of day

A raw irradiance reading of 200 W/m² could mean thick cloud at noon or clear sky at 6 pm.
Those are completely different for drying, so the measurement is compared against the
clear-sky value for the sun's current elevation:

```
clear_sky    = 1050 × sin(elevation)
sky_fraction = clamp(measured / clear_sky, 0, 1)
```

1050 W/m² is a standard approximation for peak clear-sky irradiance at sea level with the sun
overhead. `sky_fraction` then reads as "the proportion of available sun actually getting
through" — a cloud-transmission figure, independent of time of day.

Below a modelled clear-sky value of 20 W/m², the ratio is meaningless (small numbers divided
by smaller ones) and `sky_fraction` is forced to zero.

### Gating by elevation

Low sun is bright but glancing: it strikes the washing at a shallow angle, spreading the same
energy over more area, and it is filtered through much more atmosphere. So its contribution is
ramped in:

```
gate = clamp((elevation − 10) / 30, 0, 1)
```

Nothing below 10°, full effect from 40° up.

This gate matters more than it looks. In the production snapshot the sun was measurably
present — `sky_fraction` was 0.30 — but at 8.5° elevation the gate was 0, so the sun factor
was exactly 1.0 and the model correctly declined to credit it. There is a test for precisely
that distinction, because "no sun" and "sun at the wrong angle" are different states that
happen to produce the same score.

### The coefficient

```
sun_factor = 1 + SUN_COEFF × sky_fraction × gate
```

At the default `SUN_COEFF = 1.2`, full clear midday sun gives a factor of 2.2 — the exposed
line dries a little over twice as fast as the same air under cover.

**Confidence: this is the weakest number in the model, and it is exposed in the options flow
for exactly that reason.** It was chosen conservatively: it currently keeps the exposed line
below a good sunroom in most conditions. If the sunny line consistently outperforms what the
card predicted, raise it. If it over-promises, lower it.

### Forecast hours have no irradiance

Future hours carry no measurement, so sunshine must be inferred:

| Model | Condition | Formula | Ceiling |
|---|---|---|---|
| `uv` | provider gives `uv_index` | `1 + (SUN_COEFF/2) × min(uv,5)/5` | 1.6 |
| `cloud` | provider gives `cloud_coverage` | `1 + SUN_COEFF × (1−cloud/100) × gate` | 2.2 |
| `elevation` | neither | `1 + SUN_COEFF × gate` | 2.2 |

The UV model is expressed as `SUN_COEFF/2` rather than a hard-coded `0.6` so that the single
tunable moves the live and forecast scales together. At the default it is bit-identical to the
implementation this was ported from, so tuning changes nothing on day one — but raising the
coefficient no longer widens the gap between the score on screen and the scale the timings are
computed on. `diagnostics.sun_scale_ratio` reports that divergence so it can be measured
rather than argued about.

**The `cloud` fallback is not optional polish.** Met.no — free, worldwide, and built into Home
Assistant — returns no UV index at all. A UV-only model would sit at 1.0 for every hour
forever, and "move it outside at" would never fire for a large share of users. `auto` picks
`uv` when at least half the hours carry one, `cloud` when at least half carry cloud cover, and
`elevation` otherwise.

---

## 4. Rain

**Now:** wet if the rain sensor reads anything other than its configured dry word, *or* rain
rate exceeds 0.2 mm/h. A wet exposed line scores zero.

An *unknown* rain sensor reading is treated as **dry**, not wet. The sensor this was built
against is a template sensor with no unique ID, so it goes unavailable on every template
reload; zeroing the score each time would be far noisier than a brief optimistic reading, and
rain rate is an independent backstop that catches actual rain.

**Forecast:** wet at ≥50% probability or ≥0.5 mm.

A wet forecast hour zeroes the exposed line but **not** the covered line. That is deliberate
and is the whole point of a roof — it is what makes "move it under cover" useful advice when
rain is coming.

---

## 5. Bands

| Band | Score | Marker |
|---|---|---|
| Fast | ≥ 12 hPa | `●●●` |
| Moderate | ≥ 6 hPa | `●●○` |
| Slow | ≥ 3 hPa | `●○○` |
| Barely | below 3 | `○○○` |

All three thresholds are adjustable, validated as strictly descending.

### Why not hours-to-dry

Converting VPD to a drying time requires a mass-transfer coefficient that varies with fabric
weight, weave, garment geometry and how heavily the line is loaded. A towel and a shirt in
identical air dry at very different rates.

None of those have been measured here. An hours figure would be a single invented constant
presented to three significant figures — more satisfying to read and less true. Bands are what
the model can actually defend, so bands are what it reports.

This is revisitable: a fortnight of timed real loads would give the constant, and it would then
be an honest number.

---

## 6. Derived answers

### Recommendation

```
if sun_score ≥ best_indoor × 1.15 and sun_score ≥ cover_score:  "Line in the sun"
elif best_indoor ≥ cover_score:                                  <that room>
else:                                                            "Line under cover"
```

The **1.15 margin** is hysteresis, not physics. Without it, cloud crossing the sun swings the
exposed score either side of the room score and the recommendation changes every couple of
minutes. Requiring outside to be 15% better means it only wins when it is properly worth
carrying a basket out.

### Move outside at

First forecast hour where `sun > best_indoor × 1.15`, capped at sunset. `None` when no hour
qualifies — which is a real answer, "not worth it today", and the card says so in those words.

### Bring in by

First forecast hour before sunset where `max(sun, cover) < 2.5`, otherwise sunset itself.

`max(sun, cover)` because the line is movable: as long as *either* position is still drying,
there is a reason to leave the washing out.

**This is computed with no reference to `move_outside_at`, and that independence is
load-bearing.** In the implementation this was ported from, the bring-in time was gated on the
move-outside time having found a slot — so on days when going outside was never worthwhile,
the bring-in time was wiped along with it. That is precisely the day it matters most: a load
already on the line, and the only question worth answering is when to rescue it.

The fix is structural rather than careful. `calc.bring_in_by()` takes no `move_at` parameter,
so the coupling cannot be reintroduced without changing a signature, and
`test_bring_in_by_is_independent_of_move_outside_at` asserts a real time comes back from a
series where nothing ever beats indoors. A property test also checks it never returns `None`
across randomly generated series.

### Best window

The peak `sun` hour, expanded outwards while neighbouring hours still score ≥60% of the peak,
**stopping at the first dip** rather than skipping over it. A good afternoon and a good
tomorrow morning are two windows, not one long one.

Formatted with the weekday leading — `Sun 11:00-16:00 (peak 16.2)` — because with a 48-hour
horizon the best window is regularly tomorrow, and dropping the day would be actively
misleading.

### Overnight dew

The minimum forecast temperature over night hours (18:00–08:00 local) within the next 20
hours, compared against the current dew point. If the air cools below its dew point, moisture
condenses back onto the washing and a load that was dry at dusk is damp by morning.

All hour-of-day logic here is **local time**. The test suite pins its timezone to
Australia/Melbourne for exactly this reason: a UTC-only test run would pass while the feature
was silently wrong for anyone not on UTC.

### Good drying day

```
not raining and max(sun_score, cover_score) ≥ moderate_threshold
```

Deliberately about the *outdoors*, not the best spot overall. A rainy day with an excellent
sunroom is not a good day to dry, and a headline saying otherwise over a picture of rain would
read as nonsense.

---

## 7. Smoothing

Solar irradiance is the noisiest input in the model and it multiplies the largest term.
Observed within a single afternoon as cloud crossed: **528 → 564 → 426 → 150 W/m²**.

Unsmoothed, that swings the sun factor between roughly 1.0 and 2.2, which flips the
recommendation — the exact flapping the 1.15 margin exists to prevent, reintroduced through a
different door.

A ten-minute time-constant exponential moving average is applied internally. It is
time-constant rather than fixed-weight because the coordinator's tick is not guaranteed
regular: a missed update should weight the next sample *more*, not less.

The implementation this was ported from solved the same problem with a 30-minute Statistics
helper. Requiring a non-developer to build one before the integration works is a setup
footgun, so the smoothing was absorbed into the thing being configured — with an opt-out for
people who already point at an averaged sensor.

---

## 8. Refresh rates

| | Interval | Why |
|---|---|---|
| Live sensors | 2 minutes | All local state reads; effectively free |
| Hourly forecast | 15 minutes | The only call that costs anything; providers rarely update faster than hourly |
| Retry after a failed forecast | 20 seconds | Weather integrations often finish starting after this one |

That last row is not theoretical. Measured against a real BOM feed: this integration's first
refresh ran **half a second** before the weather integration registered its entities, and
`weather.get_forecasts` refuses an entity its service layer does not yet know. Without the
retry, every timing line stayed blank for two minutes after each restart.

Two other approaches were tried and are recorded here so nobody spends the time again:
refreshing on `EVENT_HOMEASSISTANT_STARTED` is swallowed by the coordinator's ten-second
debouncer, and watching the weather entity's *state* fires too early, because the state object
appears before the service layer will accept the entity.

---

## 9. Known limitations

- **The sun coefficient is untuned.** Deliberately conservative, exposed in the options, and
  the first thing to calibrate against real loads.
- **The ventilation coefficients are unvalidated.** Physically reasonable, shaped for correct
  ordering, not measured.
- **No clothing model.** A towel and a shirt get the same score.
- **No load-size effect.** A crammed line dries slower than a sparse one; the model does not
  know how full yours is.
- **Indoor rooms ignore ventilation entirely.** An open window or a running dehumidifier makes
  a real difference that is invisible here — though it will partly show up through the room's
  own humidity reading.
- **Forecast sunshine is inferred, not measured**, and the UV and cloud models have different
  ceilings. `diagnostics.sun_scale_ratio` exists to measure that drift over a season.
