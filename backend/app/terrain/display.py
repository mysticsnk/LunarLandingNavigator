"""Build bounded local ENU display grids from numerical terrain samples."""

from __future__ import annotations

import math

from app.terrain.model import MOON_REFERENCE_RADIUS_M, normalize_longitude_exact


def build_heightmap(region, terrain_source):
    latitude = float(region["origin_latitude"])
    longitude = normalize_longitude_exact(float(region["origin_longitude"]))
    spacing = float(region["spacing_m"])
    half_extent = float(region["grid_half_extent_m"])
    intervals = 2 * round(half_extent / spacing)
    if (
        not math.isfinite(spacing)
        or spacing <= 0.0
        or not math.isfinite(half_extent)
        or half_extent <= 0.0
        or not math.isclose(intervals * spacing, 2 * half_extent, abs_tol=1e-8)
        or intervals > 256
    ):
        raise ValueError("terrain display grid dimensions are invalid or exceed the size limit")

    latitude_rad, longitude_rad = math.radians(latitude), math.radians(longitude)
    up = (
        math.cos(latitude_rad) * math.cos(longitude_rad),
        math.cos(latitude_rad) * math.sin(longitude_rad),
        math.sin(latitude_rad),
    )
    east = (-math.sin(longitude_rad), math.cos(longitude_rad), 0.0)
    north = (
        -math.sin(latitude_rad) * math.cos(longitude_rad),
        -math.sin(latitude_rad) * math.sin(longitude_rad),
        math.cos(latitude_rad),
    )
    width = height = intervals + 1
    target_ups = []
    sample_latitudes = []
    sample_longitudes = []
    for row in range(height):
        north_m = -half_extent + row * spacing
        for col in range(width):
            east_m = -half_extent + col * spacing
            distance = math.hypot(east_m, north_m)
            if distance == 0.0:
                sample_latitude, sample_longitude = latitude, longitude
                target_up = up
            else:
                tangent = tuple(
                    (east_m * east[index] + north_m * north[index]) / distance for index in range(3)
                )
                angle = distance / MOON_REFERENCE_RADIUS_M
                target_up = tuple(
                    up[index] * math.cos(angle) + tangent[index] * math.sin(angle)
                    for index in range(3)
                )
                sample_latitude = math.degrees(
                    math.atan2(target_up[2], math.hypot(target_up[0], target_up[1]))
                )
                sample_longitude = normalize_longitude_exact(
                    math.degrees(math.atan2(target_up[1], target_up[0]))
                )
            target_ups.append(target_up)
            sample_latitudes.append(sample_latitude)
            sample_longitudes.append(sample_longitude)

    sample_many = getattr(terrain_source, "sample_many", None)
    surface_elevations = (
        sample_many(sample_latitudes, sample_longitudes)
        if sample_many
        else [
            terrain_source.sample(sample_latitude, sample_longitude)
            for sample_latitude, sample_longitude in zip(
                sample_latitudes, sample_longitudes, strict=True
            )
        ]
    )
    origin_index = (height // 2) * width + width // 2
    origin_elevation = surface_elevations[origin_index]
    origin_position = tuple(value * (MOON_REFERENCE_RADIUS_M + origin_elevation) for value in up)
    elevations = []
    for target_up, surface_elevation in zip(target_ups, surface_elevations, strict=True):
        position = tuple(
            value * (MOON_REFERENCE_RADIUS_M + surface_elevation) for value in target_up
        )
        delta = tuple(position[index] - origin_position[index] for index in range(3))
        elevations.append(sum(delta[index] * up[index] for index in range(3)))

    return {
        "region_id": region["region_id"],
        "dataset_id": region["id"],
        "model_version": region["processing_version"],
        "frame": "local_enu",
        "origin": {
            "latitude": latitude,
            "longitude": longitude,
            "elevation_m": origin_elevation,
        },
        "east_min_m": -half_extent,
        "north_min_m": -half_extent,
        "spacing_m": spacing,
        "width": width,
        "height": height,
        "elevation_m": elevations,
        "source_url": region["source_url"],
        "attribution": region["attribution"],
    }
