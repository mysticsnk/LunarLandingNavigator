import hashlib
import json
import math
import re
import struct
from base64 import urlsafe_b64decode, urlsafe_b64encode
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    delete,
    insert,
    null,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.astronomy import normalize_longitude
from app.core.database import get_engine
from app.core.problems import APIProblem
from app.requests import (
    CatalogSite,
    ComparisonRequest,
    NowRequest,
    TimelineRequest,
    canonical_time,
)

MODEL_VERSION = "geometric-now-v1"
TIMELINE_MODEL_VERSION = "geometric-timeline-v1"
COMPARISON_MODEL_VERSION = "comparison-v1"
TERRAIN_PROCESSING_VERSION = "lunar-south-polar-v1"
metadata = MetaData()
json_type = JSON().with_variant(JSONB(), "postgresql")
sites = Table(
    "sites",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("category", String, nullable=False),
    Column("latitude", Float, nullable=False),
    Column("longitude", Float, nullable=False),
    Column("description", String, nullable=False),
    Column("source_url", String, nullable=False),
    Column("quickmap_url", String),
    Column("terrain_region_id", String),
    CheckConstraint("latitude >= -90 AND latitude <= 90"),
    CheckConstraint("longitude >= -180 AND longitude < 180"),
    CheckConstraint("category IN ('artemis','apollo','clps','international')"),
)
jobs = Table(
    "observation_jobs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("kind", String, nullable=False),
    Column("status", String, nullable=False),
    Column("request_id", String(36), nullable=False),
    Column("submitted", json_type, nullable=False),
    Column("normalized", json_type, nullable=False),
    Column("cache_key", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    Column("result", json_type),
    Column("error", json_type),
    Column("lease_token", String(36)),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("attempts", Integer, nullable=False),
    Column("result_expires_at", DateTime(timezone=True)),
    CheckConstraint("kind IN ('now','timeline','comparison')", name="ck_observation_jobs_kind"),
    CheckConstraint("status IN ('queued','running','succeeded','failed')"),
)
Index("ix_jobs_queue", jobs.c.status, jobs.c.created_at)
Index("ix_jobs_lease", jobs.c.status, jobs.c.lease_expires_at)
Index("ix_jobs_expiry", jobs.c.result_expires_at)
observation_cache = Table(
    "observation_cache",
    metadata,
    Column("key", String(64), primary_key=True),
    Column("payload", json_type, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)
Index("ix_observation_cache_expiry", observation_cache.c.expires_at)
resource_cache = Table(
    "resource_cache",
    metadata,
    Column("key", String, primary_key=True),
    Column("payload", json_type, nullable=False),
    Column("fetched_at", DateTime(timezone=True), nullable=False),
)
terrain_datasets = Table(
    "terrain_datasets",
    metadata,
    Column("id", String, primary_key=True),
    Column("product_version", String),
    Column("source_url", String, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("asset_path", String, nullable=False),
    Column("processing_version", String, nullable=False),
    Column("resolution_m", Float, nullable=False),
    Column("retrieved_at", DateTime(timezone=True), nullable=False),
    Column("attribution", String, nullable=False),
    Column("ready", Integer, nullable=False),
    CheckConstraint("length(sha256) = 64"),
    CheckConstraint("resolution_m > 0"),
    CheckConstraint("ready IN (0,1)"),
)
terrain_regions = Table(
    "terrain_regions",
    metadata,
    Column("id", String, primary_key=True),
    Column("dataset_id", String, ForeignKey("terrain_datasets.id")),
    Column("origin_latitude", Float, nullable=False),
    Column("origin_longitude", Float, nullable=False),
    Column("spacing_m", Float, nullable=False),
    Column("grid_half_extent_m", Float, nullable=False),
    CheckConstraint("origin_latitude >= -90 AND origin_latitude <= 90"),
    CheckConstraint("origin_longitude >= -180 AND origin_longitude < 180"),
    CheckConstraint("spacing_m > 0"),
    CheckConstraint("grid_half_extent_m > 0"),
)
Index("ix_terrain_regions_dataset", terrain_regions.c.dataset_id)


def utcnow():
    return datetime.now(UTC)


def as_utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def iso(value):
    return as_utc(value).isoformat().replace("+00:00", "Z") if value else None


def request_key(normalized):
    kind = normalized.get("kind", "now")
    if kind == "comparison":
        return hashlib.sha256(
            json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    request_fields = (
        ("start_time", "duration_days", "step_minutes") if kind == "timeline" else ("target_time",)
    )
    scientific = {
        **{
            key: normalized[key]
            for key in (
                *request_fields,
                "observer_height_m",
                "visibility_margin_deg",
                "horizon_mode",
                "model_version",
                "terrain_dataset_id",
                "processing_version",
            )
            if key in normalized
        },
    }
    if kind != "now":
        scientific["kind"] = kind
    scientific.update(
        {key: normalized["site"][key] for key in ("latitude", "longitude", "surface_elevation_m")}
    )
    return hashlib.sha256(json.dumps(scientific, sort_keys=True).encode()).hexdigest()


class Repository:
    def __init__(self, engine, clock=utcnow):
        self.engine = engine
        self.clock = clock

    def site(self, site_id):
        with self.engine.connect() as conn:
            row = conn.execute(select(sites).where(sites.c.id == site_id)).mappings().first()
        if row is None:
            raise APIProblem(404, "SITE_NOT_FOUND", "Site was not found")
        return dict(row)

    def list_sites(self, category, limit, offset):
        from sqlalchemy import func

        predicate = sites.c.category == category if category else True
        with self.engine.connect() as conn:
            total = conn.scalar(select(func.count()).select_from(sites).where(predicate))
            items = (
                conn.execute(
                    select(sites).where(predicate).order_by(sites.c.id).limit(limit).offset(offset)
                )
                .mappings()
                .all()
            )
        return {
            "items": [dict(row) for row in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def resolve(self, request: NowRequest | TimelineRequest | ComparisonRequest, submitted=None):
        if isinstance(request, ComparisonRequest):
            return self.resolve_comparison(request)
        if isinstance(request.site, CatalogSite):
            record = self.site(request.site.site_id)
            preferred_region = record["terrain_region_id"]
            site = {
                "site_id": record["id"],
                **{k: record[k] for k in ("name", "latitude", "longitude")},
            }
        else:
            preferred_region = None
            site = {"site_id": None, **request.site.model_dump()}
        site["latitude"] = float(site["latitude"])
        site["longitude"] = normalize_longitude(float(site["longitude"]))
        terrain_dataset = None
        terrain_region_id = None
        if request.horizon_mode == "terrain":
            terrain_dataset, reason = self.terrain_dataset_for(
                site["latitude"], site["longitude"], preferred_region
            )
            if terrain_dataset is None:
                raise APIProblem(
                    422,
                    "TERRAIN_UNAVAILABLE",
                    "Terrain data is unavailable for the requested location.",
                    [{"field": "site", "reason": reason}],
                )
            site["surface_elevation_m"] = terrain_dataset["surface_elevation_m"]
            terrain_region_id = terrain_dataset["region_id"]
        else:
            site["surface_elevation_m"] = 0.0
        site["observer_height_m"] = request.observer_height_m
        if isinstance(request, TimelineRequest):
            start_time = canonical_time(iso(request.start_time))
            return {
                "kind": "timeline",
                "site": site,
                "start_time": start_time,
                "end_time": iso(request.start_time + timedelta(days=request.duration_days)),
                "duration_days": request.duration_days,
                "step_minutes": request.step_minutes,
                "observer_height_m": request.observer_height_m,
                "visibility_margin_deg": request.visibility_margin_deg,
                "horizon_mode": request.horizon_mode,
                "model_version": TIMELINE_MODEL_VERSION
                if terrain_dataset is None
                else terrain_dataset["processing_version"],
                **(
                    {}
                    if terrain_dataset is None
                    else {
                        "terrain_dataset_id": terrain_dataset["id"],
                        "processing_version": terrain_dataset["processing_version"],
                        "terrain_region_id": terrain_region_id,
                    }
                ),
            }
        return {
            "kind": "now",
            "site": site,
            "target_time": canonical_time(
                submitted["target_time"] if submitted else iso(request.target_time)
            ),
            "observer_height_m": request.observer_height_m,
            "visibility_margin_deg": request.visibility_margin_deg,
            "horizon_mode": request.horizon_mode,
            "model_version": MODEL_VERSION
            if terrain_dataset is None
            else terrain_dataset["processing_version"],
            **(
                {}
                if terrain_dataset is None
                else {
                    "terrain_dataset_id": terrain_dataset["id"],
                    "processing_version": terrain_dataset["processing_version"],
                    "terrain_region_id": terrain_region_id,
                }
            ),
        }

    def resolve_comparison(self, request: ComparisonRequest):
        scenarios = []
        for index, scenario in enumerate(request.scenarios):
            timeline_request = TimelineRequest(
                site=scenario.site,
                start_time=iso(scenario.start_time),
                duration_days=request.duration_days,
                step_minutes=request.step_minutes,
                horizon_mode=request.horizon_mode,
                observer_height_m=request.observer_height_m,
                visibility_margin_deg=request.visibility_margin_deg,
            )
            try:
                normalized = self.resolve(timeline_request)
            except APIProblem as exc:
                if exc.code == "TERRAIN_UNAVAILABLE":
                    raise APIProblem(
                        exc.status,
                        exc.code,
                        exc.message,
                        [
                            {
                                **detail,
                                "field": f"scenarios.{index}.site",
                            }
                            for detail in exc.details
                        ],
                    ) from exc
                raise
            normalized.pop("kind")
            normalized["label"] = scenario.label
            scenarios.append(normalized)
        dataset_ids = {scenario.get("terrain_dataset_id") for scenario in scenarios}
        return {
            "kind": "comparison",
            "scenarios": scenarios,
            "duration_days": request.duration_days,
            "step_minutes": request.step_minutes,
            "horizon_mode": request.horizon_mode,
            "observer_height_m": request.observer_height_m,
            "visibility_margin_deg": request.visibility_margin_deg,
            "ranking_version": "v1",
            "model_version": COMPARISON_MODEL_VERSION,
            "terrain_dataset_id": next(iter(dataset_ids)) if len(dataset_ids) == 1 else None,
        }

    def terrain_dataset(self, dataset_id):
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(terrain_datasets).where(
                        terrain_datasets.c.id == dataset_id,
                        terrain_datasets.c.ready == 1,
                    )
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def register_terrain_dataset(self, manifest):
        from tools.prepare_terrain import PRODUCTS, verify_raster

        asset_path = Path(manifest["path"]).resolve(strict=True)
        repository_root = Path(__file__).resolve().parents[2]
        if asset_path.is_relative_to(repository_root):
            raise ValueError("prepared terrain assets must be stored outside the repository")
        if manifest.get("preparation_status") != "terrain_ready":
            raise ValueError("terrain source has not passed raster readiness checks")
        product = PRODUCTS.get(manifest.get("product_id"))
        if product is None or product.product_id != "LDEM_80S_20MPP_ADJ.TIF":
            raise ValueError("only the verified Product 90 regional raster is registerable")
        verified = verify_raster(product, asset_path, manifest.get("sha256"))
        if manifest.get("preparation_status") != verified["preparation_status"]:
            raise ValueError("terrain source manifest does not match the verified raster")
        sha256 = verified["sha256"]
        dataset_id = f"lola-product-90-{sha256[:16]}"
        with self.engine.begin() as conn:
            if conn.scalar(
                select(terrain_datasets.c.id).where(terrain_datasets.c.id == dataset_id)
            ):
                return dataset_id
            site_rows = (
                conn.execute(select(sites).where(sites.c.terrain_region_id.is_not(None)))
                .mappings()
                .all()
            )
            if not site_rows:
                raise ValueError("apply the Stage 4 migration before registering terrain")
            conn.execute(
                insert(terrain_datasets).values(
                    id=dataset_id,
                    product_version=manifest.get("version"),
                    source_url=manifest["source_url"],
                    sha256=sha256,
                    asset_path=str(asset_path),
                    processing_version=TERRAIN_PROCESSING_VERSION,
                    resolution_m=float(manifest["resolution_m"]),
                    retrieved_at=self.clock(),
                    attribution="NASA Goddard Space Flight Center LOLA, PGDA Product 90",
                    ready=1,
                )
            )
            for row in site_rows:
                values = {
                    "dataset_id": dataset_id,
                    "origin_latitude": row["latitude"],
                    "origin_longitude": row["longitude"],
                    "spacing_m": float(manifest["resolution_m"]),
                    "grid_half_extent_m": 1280.0,
                }
                updated = conn.execute(
                    update(terrain_regions)
                    .where(terrain_regions.c.id == row["terrain_region_id"])
                    .values(**values)
                )
                if not updated.rowcount:
                    conn.execute(
                        insert(terrain_regions).values(id=row["terrain_region_id"], **values)
                    )
        return dataset_id

    def terrain_dataset_for(self, latitude, longitude, preferred_region_id=None):
        from app.terrain import TerrainCoverageError, TerrainHorizonService
        from app.terrain.raster import GeoTiffTerrainSource

        with self.engine.connect() as conn:
            if preferred_region_id:
                rows = (
                    conn.execute(
                        select(terrain_datasets, terrain_regions.c.id.label("region_id"))
                        .join(
                            terrain_regions, terrain_regions.c.dataset_id == terrain_datasets.c.id
                        )
                        .where(
                            terrain_datasets.c.ready == 1,
                            terrain_regions.c.id == preferred_region_id,
                        )
                        .order_by(terrain_datasets.c.id)
                    )
                    .mappings()
                    .all()
                )
            else:
                rows = (
                    conn.execute(
                        select(terrain_datasets)
                        .where(terrain_datasets.c.ready == 1)
                        .order_by(terrain_datasets.c.id)
                    )
                    .mappings()
                    .all()
                )
        if not rows:
            return None, "no_data"
        unavailable_reason = "outside_coverage"
        for row in rows:
            record = dict(row)
            try:
                with GeoTiffTerrainSource(
                    Path(record["asset_path"]),
                    dataset_id=record["id"],
                    model_version=record["processing_version"],
                    source_url=record["source_url"],
                    source_frame="MOON_ME / JPL DE421",
                    reference_radius_m=1_737_400.0,
                ) as source:
                    service = TerrainHorizonService(source, latitude=latitude, longitude=longitude)
                    record["surface_elevation_m"] = service.observer_surface.surface_elevation_m
                record["region_id"] = (
                    preferred_region_id
                    or "custom-"
                    + urlsafe_b64encode(record["id"].encode()).decode().rstrip("=")
                    + "-"
                    + struct.pack("!dd", latitude, normalize_longitude(longitude)).hex()
                )
                return record, None
            except TerrainCoverageError as exc:
                if exc.reason == "no_data":
                    unavailable_reason = "no_data"
                continue
            except (OSError, ValueError) as exc:
                raise APIProblem(
                    503, "TERRAIN_DATA_UNAVAILABLE", "Prepared terrain data could not be read"
                ) from exc
        return None, unavailable_reason

    def terrain_coverage(self, latitude, longitude):
        normalized_latitude = float(latitude)
        normalized_longitude = normalize_longitude(float(longitude))
        record, reason = self.terrain_dataset_for(normalized_latitude, normalized_longitude)
        if record is None:
            return {
                "available": False,
                "latitude": normalized_latitude,
                "longitude": normalized_longitude,
                "region_id": None,
                "dataset_id": None,
                "resolution_m": None,
                "source_url": None,
                "reason": reason,
            }
        return {
            "available": True,
            "latitude": normalized_latitude,
            "longitude": normalized_longitude,
            "region_id": record["region_id"],
            "dataset_id": record["id"],
            "resolution_m": record["resolution_m"],
            "source_url": record["source_url"],
            "reason": None,
        }

    def heightmap(self, region_id):
        from app.terrain.display import build_heightmap
        from app.terrain.horizon import TerrainCoverageError
        from app.terrain.raster import GeoTiffTerrainSource

        if region_id.startswith("custom-"):
            match = re.fullmatch(r"custom-([A-Za-z0-9_-]+)-([0-9a-f]{32})", region_id)
            if match is None:
                raise APIProblem(404, "REGION_NOT_FOUND", "Terrain region was not found")
            encoded_id, coordinate_hex = match.groups()
            encoded_id += "=" * (-len(encoded_id) % 4)
            try:
                dataset_id = urlsafe_b64decode(encoded_id).decode("utf-8")
                latitude, longitude = struct.unpack("!dd", bytes.fromhex(coordinate_hex))
            except (ValueError, UnicodeDecodeError, struct.error) as exc:
                raise APIProblem(404, "REGION_NOT_FOUND", "Terrain region was not found") from exc
            if (
                not math.isfinite(latitude)
                or not math.isfinite(longitude)
                or not -90 <= latitude <= 90
                or not -180 <= longitude < 180
            ):
                raise APIProblem(404, "REGION_NOT_FOUND", "Terrain region was not found")
            record = self.terrain_dataset(dataset_id)
            if record is None:
                raise APIProblem(404, "REGION_NOT_FOUND", "Terrain region was not found")
            record.update(
                region_id=region_id,
                origin_latitude=latitude,
                origin_longitude=longitude,
                spacing_m=record["resolution_m"],
                grid_half_extent_m=1280.0,
            )
        else:
            with self.engine.connect() as conn:
                row = (
                    conn.execute(
                        select(terrain_datasets, terrain_regions)
                        .join(
                            terrain_regions, terrain_regions.c.dataset_id == terrain_datasets.c.id
                        )
                        .where(terrain_regions.c.id == region_id, terrain_datasets.c.ready == 1)
                        .order_by(terrain_datasets.c.id)
                    )
                    .mappings()
                    .first()
                )
            if row is None:
                raise APIProblem(404, "REGION_NOT_FOUND", "Terrain region was not found")
            record = dict(row)
            record["region_id"] = region_id

        try:
            with GeoTiffTerrainSource(
                Path(record["asset_path"]),
                dataset_id=record["id"],
                model_version=record["processing_version"],
                source_url=record["source_url"],
                source_frame="MOON_ME / JPL DE421",
                reference_radius_m=1_737_400.0,
            ) as source:
                return build_heightmap(record, source)
        except TerrainCoverageError as exc:
            raise APIProblem(
                422,
                "TERRAIN_UNAVAILABLE",
                "Terrain data is unavailable for the requested location.",
                [{"field": "region_id", "reason": exc.reason}],
            ) from exc

    def submit(self, request, request_id, submitted=None):
        normalized = self.resolve(request, submitted)
        kind = normalized["kind"]
        job_id = str(uuid4())
        with self.engine.begin() as conn:
            conn.execute(
                insert(jobs).values(
                    id=job_id,
                    kind=kind,
                    status="queued",
                    request_id=request_id,
                    submitted=submitted
                    if submitted is not None
                    else request.model_dump(mode="json"),
                    normalized=normalized,
                    cache_key=request_key(normalized),
                    created_at=self.clock(),
                    attempts=0,
                )
            )
        return {
            "job_id": job_id,
            "kind": kind,
            "status": "queued",
            "status_url": f"/api/v1/jobs/{job_id}",
            "result_url": f"/api/v1/jobs/{job_id}/result",
        }

    def job(self, job_id):
        with self.engine.connect() as conn:
            row = conn.execute(select(jobs).where(jobs.c.id == str(job_id))).mappings().first()
        if row is None:
            raise APIProblem(404, "JOB_NOT_FOUND", "Job was not found")
        return dict(row)

    def status(self, job_id):
        job = self.job(job_id)
        return {
            "job_id": job["id"],
            "kind": job["kind"],
            "status": job["status"],
            **{key: iso(job[key]) for key in ("created_at", "started_at", "finished_at")},
            "result_url": f"/api/v1/jobs/{job_id}/result",
            "error": job["error"],
        }

    def result(self, job_id):
        job = self.job(job_id)
        if job["result_expires_at"] and as_utc(job["result_expires_at"]) <= self.clock():
            raise APIProblem(410, "JOB_EXPIRED", "Job result has expired")
        if job["status"] == "failed":
            raise APIProblem(409, "JOB_FAILED", "Job execution failed", job["error"]["details"])
        if job["status"] != "succeeded":
            raise APIProblem(409, "JOB_NOT_READY", "Job result is not ready")
        return job["result"]

    @contextmanager
    def provider_lock(self, key):
        with self.engine.connect() as conn:
            acquired = True
            if conn.dialect.name == "postgresql":
                from sqlalchemy import text

                acquired = bool(
                    conn.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
                )
            try:
                yield acquired
            finally:
                if acquired and conn.dialect.name == "postgresql":
                    conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})

    def claim(self, lease_seconds):
        now = self.clock()
        with self.engine.begin() as conn:
            conn.execute(
                update(jobs)
                .where(
                    jobs.c.status == "running",
                    jobs.c.lease_expires_at <= now,
                )
                .values(status="queued", started_at=None, lease_token=None, lease_expires_at=None)
            )
            expired_jobs = (
                select(jobs.c.id)
                .where(
                    jobs.c.result_expires_at <= now,
                    jobs.c.result.is_not(None),
                )
                .limit(100)
            )
            conn.execute(update(jobs).where(jobs.c.id.in_(expired_jobs)).values(result=null()))
            expired_cache = (
                select(observation_cache.c.key)
                .where(
                    observation_cache.c.expires_at <= now,
                )
                .limit(100)
            )
            conn.execute(
                delete(observation_cache).where(observation_cache.c.key.in_(expired_cache))
            )
            row = (
                conn.execute(
                    select(jobs)
                    .where(jobs.c.status == "queued")
                    .order_by(jobs.c.created_at, jobs.c.id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            token = str(uuid4())
            conn.execute(
                update(jobs)
                .where(jobs.c.id == row["id"])
                .values(
                    status="running",
                    started_at=now,
                    lease_token=token,
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                    attempts=row["attempts"] + 1,
                )
            )
            return {**dict(row), "lease_token": token}

    def cache_result(self, key):
        with self.engine.connect() as conn:
            return conn.scalar(
                select(observation_cache.c.payload).where(
                    observation_cache.c.key == key,
                    observation_cache.c.expires_at > self.clock(),
                )
            )

    def upsert(self, conn, table, key, **values):
        statement = (pg_insert if conn.dialect.name == "postgresql" else sqlite_insert)(table)
        conn.execute(
            statement.values(key=key, **values).on_conflict_do_update(
                index_elements=[table.c.key],
                set_=values,
            )
        )

    def finish(self, job, *, result=None, error=None, cache_seconds=3600, retention_days=7):
        now = self.clock()
        with self.engine.begin() as conn:
            updated = conn.execute(
                update(jobs)
                .where(
                    jobs.c.id == job["id"],
                    jobs.c.status == "running",
                    jobs.c.lease_token == job["lease_token"],
                    jobs.c.lease_expires_at > now,
                )
                .values(
                    status="failed" if error else "succeeded",
                    result=result,
                    error=error,
                    finished_at=now,
                    lease_token=None,
                    lease_expires_at=None,
                    result_expires_at=now + timedelta(days=retention_days) if result else None,
                )
            )
            if updated.rowcount and result and result["meta"]["data_status"] == "fresh":
                self.upsert(
                    conn,
                    observation_cache,
                    job["cache_key"],
                    payload=result,
                    expires_at=now + timedelta(seconds=cache_seconds),
                )
            return updated.rowcount == 1

    def resource(self, key):
        with self.engine.connect() as conn:
            row = (
                conn.execute(select(resource_cache).where(resource_cache.c.key == key))
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def save_resource(self, key, payload, fetched_at):
        with self.engine.begin() as conn:
            self.upsert(conn, resource_cache, key, payload=payload, fetched_at=fetched_at)


def get_repository():
    return Repository(get_engine())
