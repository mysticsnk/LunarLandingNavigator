from datetime import UTC, datetime, timedelta
from math import isclose
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.astronomy import ObservationPoint


class ResolvedSite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    site_id: str | None
    name: str = Field(min_length=1)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, lt=180)
    surface_elevation_m: Literal[0.0]
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
    horizon_mode: Literal["geometric"]
    time_resolution_minutes: Literal[15, 30, 60, 120, 180, 360] | None
    terrain_dataset_id: None
    sources: list[Source] = Field(min_length=1)


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
