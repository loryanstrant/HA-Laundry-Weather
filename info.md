# Laundry Weather

**Where should I hang the washing?**

Laundry Weather scores every place you could hang a load — each indoor room, the line under
cover, and the same line pulled out into the sun — and tells you which one wins right now,
when to move it outside, and when to bring it in.

It comes with a Lovelace card that shows the answer and charts how the next 24 hours will go.
The card installs and registers itself; there is no second thing to add.

## What it tells you

- **Where to hang it now**, ranked, with a plain-English drying rate for each spot
- **When to move it outside** — or that today it simply is not worth the trip
- **When to bring it in**, always, whether or not going outside was ever worthwhile
- **The best stretch** of the next two days
- **Whether dew will re-wet it** overnight
- **An hourly forecast chart** for the covered line, the sunny line and your best room

## How it decides

Drying is driven by how much more moisture the air could hold — its vapour pressure deficit —
not by temperature or humidity alone. That has a consequence most people find surprising: a
cold clear day frequently beats a warm humid one, and this will tell you so.

Wind, sunshine and rain then adjust each spot: a roof costs you the breeze and the sun, an
open line gets both. Results are reported as **Fast / Moderate / Slow / Barely** rather than
an invented "dry in about two hours", because turning the physics into a time needs
calibration nobody has done yet.

## What you need

Outdoor temperature and humidity, plus a weather entity with an **hourly** forecast. That is
the minimum, and everything else is optional and degrades gracefully.

It gets better with a local weather station (live solar readings are the biggest single
accuracy win), a temperature and humidity sensor in each drying room, and rain detection. The
README explains what each addition buys you.

## Accessibility

Nothing on the card uses colour to carry meaning. Drying rates are a fill meter plus the word
(`●●○` Moderate), and the chart separates its three lines by dash pattern, marker shape and a
direct label — so it reads correctly for colour-blind users and in every theme.
