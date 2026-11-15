# Stage 3 timeline acceptance cases

These are observable acceptance outcomes for geometric timeline intervals and
metrics. The state sequences are controlled synthetic test data; they are not
astronomical predictions. The executable fixture is
[`timeline_acceptance.json`](../../backend/tests/fixtures/timeline_acceptance.json).

## Primary 12-hour case

Period: `[2027-07-01T00:00:00Z, 2027-07-01T12:00:00Z)`. Step: two hours. Samples
are at `00:00`, `02:00`, `04:00`, `06:00`, `08:00`, and `10:00` UTC. There is no
sample at `12:00`.

| Sample hour | Golden state |
| ---: | --- |
| 0 | true |
| 2 | true |
| 4 | false |
| 6 | true |
| 8 | true |
| 10 | false |

Expected golden windows are `[00:00, 04:00)` and `[06:00, 10:00)`, each four
hours. Expected `golden_hours` is `8`; expected
`longest_golden_window_hours` is `4`. The false samples at hours 4 and 10 keep
the windows separate and do not contribute availability.

## Required window topologies

All cases use the same 12-hour period and 2-hour sample step. A true sample
represents `[sample_time, min(sample_time + 2h, end_time))`.

| Case | States at hours 0, 2, 4, 6, 8, 10 | Expected windows | Golden hours | Longest |
| --- | --- | --- | ---: | ---: |
| All false | `F F F F F F` | none | 0 | 0 |
| All true | `T T T T T T` | `[00:00, 12:00)` | 12 | 12 |
| First interval only | `T F F F F F` | `[00:00, 02:00)` | 2 | 2 |
| Last interval only | `F F F F F T` | `[10:00, 12:00)` | 2 | 2 |
| Alternating | `T F T F T F` | `[00:00, 02:00)`, `[04:00, 06:00)`, `[08:00, 10:00)` | 6 | 2 |

## Sun and Earth sequences

The independent visibility sequence uses Sun `T T F F T T` and Earth
`T F T T T F`. Golden state is the simultaneous conjunction at each sample:
`T F F F T F`. Expected sunlight windows are `[00:00, 04:00)` and
`[08:00, 12:00)`; Earth visibility is `[00:00, 02:00)` and `[04:00, 10:00)`;
golden windows are `[00:00, 02:00)` and `[08:00, 10:00)`. This case catches a
false golden interval if either body alone is visible.

For the primary case, the controlled body sequences are Sun `T T T T T F` and
Earth `T T F T T T`. They produce the requested golden sequence and expected
durations: sunlight 10h, Earth visibility 10h, golden 8h, and longest golden
segment 4h. Percentages use the full 12h period: 83.333…%, 83.333…%, and
66.666…%, respectively.

## Boundary and metric assertions

- Points are strictly chronological and exclude `end_time`.
- A sample at the period start can open a window at `start_time`.
- A true final sample ends at `end_time`, with duration ending at that boundary.
- End clipping alone does not set `next_sunset_at` or `next_earthset_at`; those
  fields require an observed adjacent `true -> false` transition before the end.
- A missing timestamp is a gap. A later true sample starts a separate window;
  the missing duration is not bridged.
- Each interval duration equals `end_time - start_time`; intervals in one list
  are chronological and do not overlap.
- Total duration for each availability type is at most the period; percentages
  are within `[0, 100]`.
- The longest golden duration equals the longest actual golden segment, or zero
  when the list is empty.
- At every point, golden state equals `sun.visible AND earth.visible`.
- Allowed resolution values are 15, 30, 60, 120, 180, and 360 minutes. Each
  produces an ordered half-open grid with the final point before `end_time`.

The contract's `duration_days` is an integer with minimum one day, so this exact
12-hour case is a controlled interval/service-helper test rather than a valid
HTTP request. The HTTP integration suite must separately exercise whole-day
requests when the timeline job route is registered.

## Integration and frontend gates

The existing controlled contract example
[`timeline-two-golden-windows.json`](../../contracts/examples/timeline-two-golden-windows.json)
is validated against the OpenAPI `TimelineResult` schema. The timeline service
also has controlled Horizons transport tests and a single-observation
consistency test. At this checkout, OpenAPI marks `POST /api/v1/ephemeris/timeline`
as planned and states it is not registered; therefore the asynchronous job,
status, persistence, cache, and result retrieval flow cannot yet be accepted.

After route/worker integration, use controlled provider rows for job/result
acceptance, then run an opt-in real Horizons comparison between timeline samples
and `POST /ephemeris/now`-equivalent service results at identical timestamps.
Do not assign visibility states from site names or geographic labels.

The current frontend `AnalyticsSlot` still displays the Stage 2 planned-state
placeholder. Timeline charts, separate interval bars, temporal-resolution
labeling, selected-sample navigation, and scene playback have no implemented
UI path to accept yet. Existing Stage 2 UI tests guard against presenting watts
or an invented solar-generation percentage; repeat that check when timeline UI
lands. Direct coordination with Denys, Yaroslav, Sasha, and Slavik was
unavailable in this work session; acceptance tests are isolated in
`backend/tests/test_timeline_acceptance.py` to avoid modifying their files.
