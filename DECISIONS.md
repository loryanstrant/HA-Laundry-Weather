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

## 2026-08-22 — Every spot is scored with the same formula

The reference implementation read the weather station's own
`vapour_pressure_deficit` sensor for the outdoor spots, while computing indoor
rooms from temperature and humidity with the Magnus formula. Two sources for
the same quantity.

This integration computes all of them the same way, from temperature and
humidity. Two reasons: most weather stations expose no VPD sensor at all, so
the station-sensor path would be a second code path serving a minority; and the
entire point of the card is ranking a room against a line, which is only
meaningful if both numbers came out of the same formula.

Measured cost: the station's firmware disagrees with Magnus by **0.0085 hPa**
(0.17%). That lands on the second decimal place of a score and is two orders of
magnitude below the width of a drying band, so it cannot change an answer. The
parity tests assert against production with that tolerance stated explicitly
rather than asserting a match that does not exist.

Worth recording separately: the design session reported the formula reproducing
the station "exactly (3.42 vs 3.42)". Measured against full precision it is
0.0085 hPa out — the exact match was rounding to two decimals. The conclusion
survives; the wording did not.

**Lesson:** "reproduces it exactly" measured at display precision is a
statement about the display. Check the residual before writing it down.

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

## 2026-08-22 — The blueprints ship inside the component and install themselves

Home Assistant loads blueprints from `config/blueprints/<domain>/` and nowhere
else — `blueprint/models.py` resolves the folder as
`hass.config.path("blueprints", domain)` — and offers integrations no API to
register one. That was read as "you cannot ship blueprints with an integration",
and the first cut left them at the repo root with an import badge, i.e. a second
manual step for a feature the card already gets for free.

Wrong conclusion. `HA-Personal-Hydration-Manager` already solves this the way
HACS does for blueprint repositories: bundle them in the component and copy them
across at setup. `blueprints_install.py` does that here, off the event loop.

> ⚠️ The guard this entry originally described — copy "only when the shipped
> file is newer than the installed one" — was wrong, and was replaced in v0.4.1.
> See *2026-10-22 — mtime is not a user-edit detector* below.

The root copy stays, because the README's import badges have to keep working for
people who have not installed the integration. Two copies of the same file is a
drift hazard, and it is not hypothetical — hydration's two copies already differ
by three bytes, silently, so the file imported by URL is not quite the file that
gets installed. A packaging test asserts they stay byte-identical here.

**Lesson:** "Home Assistant can't do that" is a claim about a codebase that is
readable, and about repos that are already on disk. Check one of them before
declining.

## 2026-08-22 — Every test gets its own config directory

`pytest-homeassistant-custom-component` points every test at a single
`testing_config/` inside site-packages. Installing blueprints for real writes
into it, so the files outlive the run: a test that edited an installed blueprint
made the test asserting the installed copy is pristine fail on the *second* run
and never the first. An autouse fixture repoints `hass.config.config_dir` at the
test's `tmp_path`.

**Lesson:** the moment an integration writes to the config directory, the shared
test config directory becomes state, and state that only bites on a rerun is the
expensive kind.

## 2026-08-23 — The headline judges the day, not the minute

`good_drying_day()` read only the live scores while its own docstring said
"Is today worth putting a load out at all?". On prod at 10:06 — 13.8 C, 65% RH,
**wind 0.0 km/h** — the exposed line scored 5.56 against a 6.0 cut, so the card
said "It Is Not a Good Day to Dry" directly above "Move outside 12:00 PM" and a
best window of 11:00-16:00 peaking at 16.6. Both statements came from the same
payload. On any cold still morning the verdict was "no" regardless of the
afternoon.

It now takes the best score still to come before tonight's sunset. Two traps
had to be avoided. `best_window` searches the whole 48-hour horizon and is
regularly *tomorrow*, so its peak could not be used directly. And the `sunset`
handed to `assess` rolls forward to the *next* sunset once today's has gone —
the same thing that produced the "bring in by, in 52 minutes" bug — so
`rest_of_today_peak` takes `day_over` for exactly the reason `bring_in_by` takes
`drying_now`.

The live scores stay in the comparison as a floor, so a thin forecast cannot
argue with an afternoon that is demonstrably drying.

**Lesson:** when a function's docstring and its arithmetic disagree about what
question is being answered, the docstring is usually the requirement and the
arithmetic is the bug.

## 2026-08-23 — The card renders its own clock times

Whether a time reads 17:54 or 5:54 PM is `hass.locale.time_format` — a per-user
*frontend* setting that never reaches Python. So the advice sentence and the
best-window text, both composed server-side with `strftime("%H:%M")`, were
stuck at 24-hour on a 12-hour dashboard, sitting directly beneath timing rows
the card had formatted correctly as "12:00 PM".

The wording still lives in one place. `build_advice_template()` emits the same
sentence with `{move_at}`, `{bring_by}` and `{window}` left open, and the card
fills them. Which clauses survive truncation is decided from the *real*
sentence, because placeholders are longer than clock times and letting each
version decide separately would let the card drop a clause the entity kept.

The entity state is unchanged, so notifications, TTS and both blueprints are
untouched.

**Lesson:** anything a person reads on a dashboard has to be formatted where
that person's preferences are known. The backend is not that place.

## 2026-08-23 — The card editor stopped rebuilding itself

The clock-format dropdown flashed open and shut. `set hass` called `_render()`,
which assigned `shadowRoot.innerHTML` wholesale, and Home Assistant assigns
`hass` on every state change — so the `<select>` the user had just opened was
destroyed and rebuilt underneath the popup several times a second. `_emit()`
re-rendered too, *and* Home Assistant echoes the change back through
`setConfig`, so one edit rendered twice.

Not dropdown-specific: the entity picker had it too, and the text fields were
silently losing focus and caret position mid-typing.

The card already had the answer — it diffs its data before re-rendering, with a
comment explaining that re-rendering loses focus. The editor now does the same,
keyed on the config plus the candidate entity list.

Verified by node identity rather than by eye: create the editor element
directly, assign `hass` twenty times, and check the `<select>` is the same node
object. 0.3.0 fails it, 0.3.1 passes. That also sidesteps the config dialog,
which never attaches in a headless browser and defeated five earlier attempts
at screenshotting the editor.

**Lesson:** when a UI bug is "it disappears", test for object identity, not for
appearance — it is cheap, headless, and it fails loudly on the old code.

## 2026-08-23 — The card editor is built on `ha-form`

The editor was 137 lines of hand-built DOM producing browser-default controls, inside a Home
Assistant dialog full of Material fields. Two `standards/ux.md` rules broken: *consistency*
(reuse the app's primitives; match the neighbours) and *copy* (no raw identifiers where a name
would do — the sensor picker listed `sensor.laundry_weather_recommendation` in the one field a
non-developer must get right).

The structural argument mattered more than the cosmetic one. v0.3.1 fixed the dropdown that
flashed open and shut by adding an equality check before re-rendering. That is a guard, and a
later edit to `_render()` could undo it. The sibling `ha-jokes` card has the identical naive
`set hass → _render()` shape and has never had the bug, because the form element is created
once and thereafter only `.hass`, `.schema` and `.data` are assigned; Lit patches in place.
There is nothing to blow away.

Three things specific to this card:

- The picker uses `include_entities` seeded with the same candidate filter the old `<select>`
  used, so the offered set is unchanged while gaining friendly names and search. Filtering by
  integration alone would have offered all nine Laundry Weather sensors, most of which the card
  cannot read.
- The Klingon setting is tri-state — `true`/`false`/`null`, where null means "follow the
  integration". A boolean selector cannot express three states, so it became a dropdown, with a
  mapping in both directions. Configs written by the old checkbox editor load unchanged.
- `_lwLoadHaComponents()` forces the frontend chunk that defines `ha-form`, copying Mushroom.
  `window.customElements` is re-read on every call and never bound at module top level: Home
  Assistant swaps it for a scoped-registry polyfill while booting, so a captured reference can
  point at the wrong registry and a top-level `whenDefined` may never fire.

**A trap found while previewing, worth more than the port.** `ha-entity-picker` renders
*nothing* — zero height, empty shadow root, no error — unless it sits inside `<home-assistant>`.
Newer HA components take `hass` from a Lit context provider rather than a property. The first
preview attached the form to `document.body` and the sensor row silently vanished while every
other field rendered. In production the editor lives inside the card dialog so it is fine, but
any harness that builds the editor directly must attach it under `<home-assistant>` or it is
testing a half-dead form.

**Lesson:** a component that renders nothing is not obviously broken. When a UI check builds
elements outside their normal parent, assert something rendered before trusting what did.

## 2026-10-22 — mtime is not a user-edit detector

HACS review (hacs/default#10258) blocked the default-repository submission on
one line of `blueprints_install.py`:

> replaces the copy in `config/blueprints/automation/loryanstrant/` whenever the
> bundled file is newer. Anyone who edited their copy loses those edits on the
> next upgrade, without warning.

Correct. The guard was `source.stat().st_mtime > destination.stat().st_mtime`,
and a HACS upgrade unzips the component fresh, so the shipped file's mtime is
*always* newer than anything already sitting in the config directory. The guard
only ever held within a single install — exactly the case that does not matter.

The test did not catch it, and the reason is the interesting part.
`test_an_edited_copy_is_not_clobbered` edited the destination *after*
installing, which left the destination the newer file, so the broken guard
passed. The test reproduced the ordering of a restart and never the ordering of
an upgrade — the only ordering the guard existed for.

v0.4.1 records a SHA-256 of every file it writes, in
`config/.storage/laundry_weather_blueprints`. A destination whose hash still
matches the record is untouched and safe to replace; anything else is the
user's and is left alone with a log line. A file with no record — anyone who
installed before v0.4.1 — is also left alone, because the bytes cannot
distinguish an old shipped version from an edited one. The cost is that those
users must re-import by hand to get an improved blueprint, which the release
notes and README both spell out; the alternative was shipping a list of every
historical hash and maintaining it forever.

Three further hazards came out of reviewing the replacement, all of which end
in the same place — a file wrongly classified as edited, and therefore frozen
forever. The once-per-run flag was being set *after* two awaits, so two config
entries set up concurrently could both reach the executor and hash files each
other was mid-write; it is now claimed before the first await. Writes go to a
temporary name and are renamed into place, so a disk that fills part-way leaves
the old file rather than a truncated one with no matching hash. And a corrupt
`.storage` record now warns instead of raising, because a side feature must not
take the drying model down with it.

`HA-Personal-Hydration-Manager` has the same installer and the same bug.

**Lesson:** a guard needs a test that reproduces the *hostile* ordering, not a
convenient one. "Edit then reinstall" and "edit, then an upgrade lands" are
different tests, and only the second one was ever the requirement.
