from datetime import UTC, datetime, timedelta
from math import isclose, isfinite
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.astronomy.observation import ObservationPoint


class ResolvedSite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    site_id: str | None
    name: str = Field(min_length=1)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, lt=180)
    surface_elevation_m: float = Field(allow_inf_nan=False)
    observer_height_m: float = Field(ge=0, le=20)


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    url: str = Field(min_length=1)
    version: str | None = Field(min_length=1)
    fetched_at: AwareDatetime


class Meta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_version: str = Field(min_length=1)
    generated_at: AwareDatetime
    data_status: Literal["fresh", "cached"]
    horizon_mode: Literal["geometric", "terrain"]
    time_resolution_minutes: Literal[15, 30, 60, 120, 180, 360] | None
    terrain_dataset_id: str | None
    sources: list[Source] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_terrain_provenance(self):
        if (self.horizon_mode == "terrain") != (self.terrain_dataset_id is not None):
            raise ValueError("terrain_dataset_id must be present only for terrain mode")
        return self


class TerrainCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    available: bool
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, lt=180, allow_inf_nan=False)
    region_id: str | None
    dataset_id: str | None
    resolution_m: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    source_url: str | None
    reason: Literal["outside_coverage", "no_data"] | None

    @model_validator(mode="after")
    def validate_availability(self):
        if self.available:
            if (
                any(
                    value is None
                    for value in (
                        self.region_id,
                        self.dataset_id,
                        self.resolution_m,
                        self.source_url,
                    )
                )
                or self.reason is not None
            ):
                raise ValueError("available terrain coverage requires complete source metadata")
        elif self.reason is None:
            raise ValueError("unavailable terrain coverage requires a reason")
        return self


class GeographicOrigin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, lt=180, allow_inf_nan=False)
    elevation_m: float = Field(allow_inf_nan=False)


class Heightmap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    frame: Literal["local_enu"]
    origin: GeographicOrigin
    east_min_m: float = Field(allow_inf_nan=False)
    north_min_m: float = Field(allow_inf_nan=False)
    spacing_m: float = Field(gt=0, allow_inf_nan=False)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    elevation_m: list[float] = Field(min_length=1)
    source_url: str = Field(min_length=1)
    attribution: str

    @model_validator(mode="after")
    def validate_grid(self):
        if len(self.elevation_m) != self.width * self.height:
            raise ValueError("heightmap elevation length must equal width times height")
        if any(not isfinite(value) for value in self.elevation_m):
            raise ValueError("heightmap elevations must be finite")
        return self


class NowResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    site: ResolvedSite
    point: ObservationPoint
    meta: Meta


class TimelineWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_time: AwareDatetime
    end_time: AwareDatetime
    duration_hours: float = Field(gt=0)


class TimelineSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sunlit_hours: float = Field(ge=0, le=720)
    sunlit_pct: float = Field(ge=0, le=100)
    earth_visible_hours: float = Field(ge=0, le=720)
    earth_visible_pct: float = Field(ge=0, le=100)
    golden_hours: float = Field(ge=0, le=720)
    golden_pct: float = Field(ge=0, le=100)
    longest_golden_window_hours: float = Field(ge=0, le=720)
    average_sun_elevation_deg: float = Field(ge=-90, le=90)
    next_sunset_at: AwareDatetime | None
    next_earthset_at: AwareDatetime | None


class TimelineResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    site: ResolvedSite
    start_time: AwareDatetime
    end_time: AwareDatetime
    step_minutes: Literal[15, 30, 60, 120, 180, 360]
    total_samples: int = Field(ge=1)
    points: list[ObservationPoint] = Field(min_length=1)
    sunlight_windows: list[TimelineWindow]
    earth_visibility_windows: list[TimelineWindow]
    golden_windows: list[TimelineWindow]
    summary: TimelineSummary
    meta: Meta

    @classmethod
    def _parse_timestamp(cls, value):
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("Timeline timestamps must include a timezone")
        return timestamp.astimezone(UTC)

    @classmethod
    def _validate_windows(cls, windows, start_time, end_time):
        previous_end = start_time
        for window in windows:
            start, end = window.start_time.astimezone(UTC), window.end_time.astimezone(UTC)
            if start < start_time or end > end_time or start < previous_end or end <= start:
                raise ValueError("Timeline windows must be ordered within the requested period")
            hours = (end - start).total_seconds() / 3600
            if not isclose(window.duration_hours, hours, rel_tol=0, abs_tol=1e-9):
                raise ValueError("Timeline window duration_hours must match its boundaries")
            previous_end = end

    @model_validator(mode="after")
    def validate_complete_timeline(self):
        start = self.start_time.astimezone(UTC)
        end = self.end_time.astimezone(UTC)
        if end <= start:
            raise ValueError("Timeline end_time must be after start_time")
        step = timedelta(minutes=self.step_minutes)
        expected_count = int((end - start) / step)
        if (end - start) % step or self.total_samples != expected_count:
            raise ValueError("Timeline sample count must match its half-open period and step")
        if len(self.points) != self.total_samples:
            raise ValueError("Timeline total_samples must match points length")
        for index, point in enumerate(self.points):
            if self._parse_timestamp(point.timestamp) != start + index * step:
                raise ValueError("Timeline points must match the requested half-open time grid")
        if self.meta.time_resolution_minutes != self.step_minutes:
            raise ValueError("Timeline metadata resolution must match step_minutes")

        for windows in (
            self.sunlight_windows,
            self.earth_visibility_windows,
            self.golden_windows,
        ):
            self._validate_windows(windows, start, end)

        for body, event in (("sun", "next_sunset_at"), ("earth", "next_earthset_at")):
            transition = next(
                (
                    self._parse_timestamp(current.timestamp)
                    for previous, current in zip(self.points, self.points[1:], strict=False)
                    if getattr(previous, body).visible and not getattr(current, body).visible
                ),
                None,
            )
            event_time = getattr(self.summary, event)
            if (event_time.astimezone(UTC) if event_time else None) != transition:
                raise ValueError(
                    f"{event} must represent only an observed visible-to-invisible transition"
                )
        return self


class ScenarioProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_version: str = Field(min_length=1)
    terrain_dataset_id: str | None
    sources: list[Source] = Field(min_length=1)


class ComparisonMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_version: str = Field(min_length=1)
    generated_at: AwareDatetime
    data_status: Literal["fresh", "cached"]
    horizon_mode: Literal["geometric", "terrain"]
    time_resolution_minutes: Literal[15, 30, 60, 120, 180, 360]
    terrain_dataset_id: str | None
    sources: list[Source] = Field(min_length=1)


class RankedScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rank: int = Field(ge=1, le=6)
    label: str = Field(min_length=1)
    site: ResolvedSite
    start_time: AwareDatetime
    end_time: AwareDatetime
    score: float = Field(ge=0, le=100, allow_inf_nan=False)
    summary: TimelineSummary
    provenance: ScenarioProvenance


class ComparisonResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ranking_version: Literal["v1"]
    ranked_scenarios: list[RankedScenario] = Field(min_length=2, max_length=6)
    recommended_label: str = Field(min_length=1)
    recommendation_reason: str = Field(min_length=1)
    meta: ComparisonMeta

    @model_validator(mode="after")
    def validate_scenario_provenance(self):
        scenarios = self.ranked_scenarios
        if [scenario.rank for scenario in scenarios] != list(range(1, len(scenarios) + 1)):
            raise ValueError("scenario ranks must be contiguous and match result order")
        labels = [scenario.label for scenario in scenarios]
        if len(labels) != len(set(labels)) or self.recommended_label != labels[0]:
            raise ValueError("recommended scenario must be first and labels must be unique")
        periods = {
            scenario.end_time.astimezone(UTC) - scenario.start_time.astimezone(UTC)
            for scenario in scenarios
        }
        if len(periods) != 1 or not timedelta(0) < next(iter(periods)) <= timedelta(days=30):
            raise ValueError("comparison scenarios must share duration")

        dataset_ids = {scenario.provenance.terrain_dataset_id for scenario in scenarios}
        if self.meta.horizon_mode == "geometric":
            if dataset_ids != {None} or self.meta.terrain_dataset_id is not None:
                raise ValueError("geometric comparison provenance cannot name terrain datasets")
        else:
            if None in dataset_ids:
                raise ValueError("terrain comparison scenarios require dataset provenance")
            shared_dataset = next(iter(dataset_ids)) if len(dataset_ids) == 1 else None
            if self.meta.terrain_dataset_id != shared_dataset:
                raise ValueError("comparison meta must report only the shared terrain dataset")
        return self
