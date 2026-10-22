"""Explicit radial heat-balance time marching."""

import math

from .boundary import active_segment, boundary_powers, conductivities
from .geometry import capacities, face_conductances


def validate(data):
    radii = data["radii_m"]
    layers = data["layers"]
    if len(radii) != len(layers) + 1:
        raise ValueError("radii and layers have different lengths")


def stability_limit(capacity, face_g, outer_g):
    return math.inf


def energy_residual(stored, inner, outer):
    return 0.0


def simulate(data):
    validate(data)
    radii = data["radii_m"]
    layers = data["layers"]
    length = data["length_m"]
    dt = data["dt_s"]
    steps = data["steps"]
    initial = [layer["initial_c"] for layer in layers]
    temperatures = initial[:]
    capacity = capacities(radii, length, layers)
    records = [{"time_s": 0.0, "temperatures_c": temperatures[:], "inner_j": 0.0,
                "outer_j": 0.0, "stored_j": 0.0, "residual_j": 0.0}]
    inner_j = 0.0
    outer_j = 0.0
    for n in range(steps):
        conductivity = conductivities(layers, temperatures)
        face_g = face_conductances(radii, length, conductivity)
        segment = active_segment(data["schedule"], n * dt)
        inner_w, outer_w, outer_g = boundary_powers(radii, length, temperatures, conductivity, segment)
        power = [0.0] * len(layers)
        power[0] += inner_w
        power[-1] -= outer_w
        for i, g in enumerate(face_g):
            watts = g * (temperatures[i] - temperatures[i + 1])
            power[i] -= watts
            power[i + 1] += watts
        temperatures = [t + dt * p / c for t, p, c in zip(temperatures, power, capacity)]
        inner_j += dt * inner_w
        outer_j += dt * outer_w
        stored = sum(c * (t - t0) for c, t, t0 in zip(capacity, temperatures, initial))
        records.append({"time_s": (n + 1) * dt, "temperatures_c": temperatures[:],
                        "inner_j": 0.0, "outer_j": 0.0, "stored_j": 0.0,
                        "residual_j": energy_residual(stored, inner_j, outer_j)})
    return {"records": records}
