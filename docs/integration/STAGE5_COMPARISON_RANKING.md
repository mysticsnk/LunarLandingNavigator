# Stage 5 Comparison Metrics and Ranking Service Handoff

## 1. Overview and Scope

This module implements the comparison evaluation and ranking service for Stage 5 of the Lunar Landing Site Navigator, strictly following the agreed v1 specification and `contracts/openapi.v1.yaml`.

It reuses validated timeline summary semantics without introducing synthetic operational data or modifying underlying astronomical algorithms.

## 2. Service Interface

Available via `app.comparison` or `app.astronomy.comparison`:

```python
from app.comparison import (
    ComparisonResult,
    RankedScenario,
    ScenarioEvaluationInput,
    build_recommendation_reason,
    calculate_v1_score,
    evaluate_comparison,
    evaluate_scenarios,
    rank_scenarios,
    validate_summary_metrics,
)
```

### Primary Interface Functions

1. **`evaluate_comparison(scenarios, meta, precision=2) -> ComparisonResult`**:
   - Takes a list of 2–6 scenarios (`ScenarioEvaluationInput` or dictionaries) and shared result metadata `ComparisonMeta`.
   - Returns a validated `ComparisonResult` object conforming to the OpenAPI v1 schema.

2. **`evaluate_scenarios(scenarios, precision=2) -> tuple[list[RankedScenario], str]`**:
   - Validates metrics, calculates unrounded v1 scores, sorts deterministically, and formats `RankedScenario` models alongside a deterministic English recommendation reason.

3. **`rank_scenarios(scenarios, precision=2) -> tuple[list[RankedScenario], list[float]]`**:
   - Sorts scenarios and returns the ranked models along with their unrounded scores.

4. **`calculate_v1_score(summary) -> float`**:
   - Validates summary assumptions and calculates the unrounded score.

5. **`validate_summary_metrics(summary) -> dict[str, float]`**:
   - Validates physical and mathematical consistency of supplied metrics without silent clamping.

6. **`build_recommendation_reason(winner, runner_up, winner_unrounded, runner_unrounded) -> str`**:
   - Generates deterministic English explanation.

### Input Scenario Structure (`ScenarioEvaluationInput`)

```python
class ScenarioEvaluationInput(BaseModel):
    label: str  # Unique scenario label (min_length=1)
    site: ResolvedSite  # Resolved lunar surface coordinates and elevation
    start_time: AwareDatetime  # Requested start instant
    end_time: AwareDatetime  # Calculated end instant (start_time + duration_days)
    summary: TimelineSummary | Summary  # Validated timeline metrics
    provenance: ScenarioProvenance  # Model, terrain dataset, and sources for this scenario
```

Convenience constructor from timeline results:
```python
scenario = ScenarioEvaluationInput.from_timeline(
    label="Shackleton Connecting Ridge",
    timeline=timeline_result,
    site=resolved_site,
)
```

## 3. Scoring Formula and Ranking Version

- **Ranking Version**: `"v1"`
- **Scoring Formula**:
  $$\text{score} = 0.40 \times \text{sunlit\_pct} + 0.30 \times \text{earth\_visible\_pct} + 0.30 \times \text{golden\_pct}$$
- **Weights**:
  - `SUNLIT_WEIGHT = 0.40`
  - `EARTH_VISIBLE_WEIGHT = 0.30`
  - `GOLDEN_WEIGHT = 0.30`

The score is a comparative product score, not an official NASA safety or landing certification.

## 4. Ranking and Deterministic Tie Behavior

Scenarios are sorted using the following strict hierarchy:
1. **Unrounded score descending**: Full floating-point precision score is evaluated first.
2. **Longest golden window descending (`longest_golden_window_hours`)**: When unrounded scores are identical.
3. **Original request order**: When both unrounded scores and longest golden windows are identical.

Ranks are assigned 1-indexed ($1, 2, \dots, N$).

## 5. Output Precision

- **Calculation & Ranking**: Performed using full unrounded floating-point precision.
- **Output Score (`RankedScenario.score`)**: Rounded to 2 decimal places by default (`precision=2`), or left unrounded if `precision=None`.
- Ranking never depends on displayed rounded values; raw score differences that round to the same display score are preserved in ranking order.

## 6. Summary Metric Assumptions and Validation

Summary inputs are strictly validated without silent clamping:
- `sunlit_pct`, `earth_visible_pct`, and `golden_pct` must be finite numbers within $[0.0, 100.0]$.
- `longest_golden_window_hours` must be finite and $\ge 0.0$.
- `golden_pct` cannot exceed `sunlit_pct` or `earth_visible_pct`.
- When `golden_hours` is provided, `longest_golden_window_hours` cannot exceed `golden_hours`.
- When golden availability is 0%, `longest_golden_window_hours` must be 0.0.

## 7. Deterministic Recommendation Rules

The `recommendation_reason` string is generated deterministically in English without LLM heuristics:
- **Winner by score**: Details the winner's score, component percentages (sunlight, Earth visibility, golden windows), and states outperformance over the runner-up using the 40/30/30 weights.
- **Tie broken by window**: States identical scores and explains that the longer continuous golden window resolved the recommendation.
- **Complete equivalence**: States that scenarios are equivalent under the ranking rules (identical score and longest window) and that original request order resolved the recommendation.
- **Certification language**: Omits any safety or NASA certification claims.

## 8. Test Verification

Tests in `backend/tests/test_stage5_comparison_ranking.py` verify:
- Required examples:
  - A: sunlit=80, Earth=60, golden=50 $\rightarrow$ 65.0
  - B: sunlit=60, Earth=80, golden=50 $\rightarrow$ 63.0
  - C: sunlit=50, Earth=50, golden=0 $\rightarrow$ 35.0
- Boundary conditions: all-zero (0.0) and all-100 (100.0) availability.
- Weight verification for 0.40 / 0.30 / 0.30 terms.
- Longest-window tie breaking with identical scores.
- Complete ties with original input order preservation.
- Raw score separation where values round to the same display score.
- Validation rejections of physical impossibilities and invalid percentages.
- Unique scenario labels and scenario count boundaries (2–6).
- Official contract example fixture parsing and validation.
