[![make.fun](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/renprayoga/gta6-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/renprayoga/gta6-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)

# GTA VI launch-day Twitch viewers — hour-by-hour forecaster

Entry for make.fun `gta6-twitch-ccu-forecast-01`: a program (`main.py`,
Python 3.13, standard library only) that reads one case
(`/input/<id>.in`) and writes `/output/<id>.out` with, for hours 2–24 of
the release day (UTC), five quantiles (5%, 25%, 50%, 75%, 95%) of the
Twitch category's concurrent viewers.

## How it works

The shape of a big launch day is mostly a question of scale. Across the
comparable launches shipped inside each case file, the ratio of each
hour's viewers to hour 1's depends overwhelmingly on how big hour 1
itself was:

- a launch whose category was nearly dead at 00:00 UTC (simultaneous
  global unlock later in the day) explodes by hundreds of times by the
  evening;
- a launch already huge at hour 1 (rolling midnight-local unlock, most of
  the world already playing) stays roughly flat and peaks only ~1.0–1.3×
  hour 1.

So for each forecast hour the program takes a kernel-weighted average of
the comparables' log-ratios `ln(viewers_h / viewers_1)`, with Gaussian
weights in `ln(hour-1 viewers)` (bandwidth 1.0 in log units) — launches
whose hour 1 was a similar size count most. The centre is the average of
the weighted median and the weighted mean of those log-ratios (median for
robustness, mean for efficiency), lightly smoothed across neighbouring
hours. The spread is the weighted standard deviation of the same
log-ratios around that centre (floored at 0.12 log units), so hours where
past launches disagree get honestly wide quantiles. Quantiles are
lognormal around the centre:
`q_tau = p1 * exp(centre_h + z_tau * sigma_h)`.

The target game's own pre-release category history (shipped as a
comparable in every case) is excluded — it is not a launch day. The
target's pre-release history was examined and deliberately not used as a
shape input: in leave-one-out tests, weighting by pre-release level made
the loss worse, and hour 1's print already carries the launch's scale.
Unlock-time text is not parsed either: the same tests showed it adds
nothing once hour-1 size is conditioned on. If a case carries no usable
comparables, the program falls back to the flat persistence forecast
(every hour at hour 1's print, spread widening like a random walk), so
the output is always valid.

## Validation

The kit's `grade-local` cannot score this competition locally — it
reports that the scorer and reference data are not published in the kit
and grading is server-only — so no practice-case loss (p00–p03) could be
measured on this machine. Instead the shipped `main.py` was validated
end-to-end by leave-one-out over the 37 comparable launches in the kit:
each comparable was rebuilt as a synthetic case (its hour-1 print known,
its own curve held out as truth, the other 37 comparables as input) and
scored with the contest's pinball loss on the log scale:

- **shipped program: 0.3944** mean pinball loss
- **flat house baseline on the same cases: 0.9297** (ratio 0.424)
- rolling-midnight-unlock subset (12 launches, the unlock shape GTA VI
  has): **0.2635**
- the program beat the flat baseline on every one of the 37 cases,
  including the worst (Black Myth: Wukong, 1.83 vs flat 3.43 — a
  simultaneous-global unlock, a shape GTA VI does not have).

These are comparable-launch figures, not practice-case scores; the real
practice score is only known after server grading. The model was tuned
only on the comparables (bandwidth 1.0 vs 0.7/1.2, mean vs median vs mix),
never on the practice cases' answers, which are not in the kit.

## Running it

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Deterministic (fixed order, no randomness, no clock, no network);
about 0.05 s per case, far inside the 8 s cap.

## Files

- `main.py` — the whole forecaster, single file
- `LICENSE` — MIT
- `.makefun/owner.json` — claim wallet
