"""Explicit radial heat-balance time marching."""

import math

from .boundary import active_segment, boundary_powers, conductivities
from .geometry import capacities, face_conductances, volumes


def _number(value, label, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    if positive and value <= 0:
        raise ValueError(f"{label} must be positive")
    if nonnegative and value < 0:
        raise ValueError(f"{label} must be nonnegative")


def validate(data):
    if not isinstance(data, dict):
        raise ValueError("input must be a JSON object")
    radii = data["radii_m"]
    layers = data["layers"]
    schedule = data["schedule"]
    if not isinstance(radii, list) or not isinstance(layers, list) or not layers or len(radii) != len(layers) + 1:
        raise ValueError("radii and layers have different lengths")
    for radius in radii:
        _number(radius, "radius", positive=True)
    if any(b <= a for a, b in zip(radii, radii[1:])):
        raise ValueError("radii must increase")
    _number(data["length_m"], "length", positive=True)
    _number(data["dt_s"], "time step", positive=True)
    steps = data["steps"]
    if isinstance(steps, bool) or not isinstance(steps, int) or steps < 0:
        raise ValueError("steps must be a nonnegative integer")
    for layer in layers:
        if not isinstance(layer, dict):
            raise ValueError("layer must be an object")
        for key in ("rho_kg_m3", "cp_j_kg_k", "k0_w_m_k"):
            _number(layer[key], key, positive=True)
        _number(layer["alpha_per_k"], "alpha")
        _number(layer["initial_c"], "initial temperature")
        _number(layer["q_gen_w_m3"], "heat generation")
    if not isinstance(schedule, list) or not schedule:
        raise ValueError("schedule is empty")
    previous = -1.0
    for segment in schedule:
        if not isinstance(segment, dict):
            raise ValueError("schedule entry must be an object")
        _number(segment["start_s"], "start time", nonnegative=True)
        if segment["start_s"] <= previous:
            raise ValueError("schedule times must increase")
        previous = segment["start_s"]
        _number(segment["inner_flux_w_m2"], "inner flux")
        _number(segment["ambient_c"], "ambient temperature")
        _number(segment["h_w_m2_k"], "convection coefficient", nonnegative=True)
        epsilon = segment["epsilon"]
        if isinstance(epsilon, bool) or not isinstance(epsilon, (int, float)) or not math.isfinite(epsilon) or not 0 <= epsilon <= 1:
            raise ValueError("emissivity must be between zero and one")
    if schedule[0]["start_s"] != 0:
        raise ValueError("schedule must start at zero")


def stability_limit(capacity, face_g, outer_g):
    limits = []
    for i, heat_capacity in enumerate(capacity):
        coupling = face_g[i - 1] if i else 0.0
        coupling += face_g[i] if i < len(face_g) else 0.0
        if i == len(capacity) - 1:
            coupling += outer_g
        limits.append(heat_capacity / coupling if coupling else math.inf)
    return min(limits)


def energy_residual(stored, inner, outer, generated):
    return stored - inner + outer - generated


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
    volume = volumes(radii, length)
    generation = [layer["q_gen_w_m3"] * vol for layer, vol in zip(layers, volume)]
    records = [{"time_s": 0.0, "temperatures_c": temperatures[:], "inner_j": 0.0,
                "outer_j": 0.0, "generated_j": 0.0, "stored_j": 0.0, "residual_j": 0.0}]
    inner_j = 0.0
    outer_j = 0.0
    generated_j = 0.0
    for n in range(steps):
        conductivity = conductivities(layers, temperatures)
        face_g = face_conductances(radii, length, conductivity)
        segment = active_segment(data["schedule"], n * dt)
        inner_w, outer_w, outer_g = boundary_powers(radii, length, temperatures, conductivity, segment)
        limit = stability_limit(capacity, face_g, outer_g)
        if dt > limit and not math.isclose(dt, limit, rel_tol=1e-12):
            raise ValueError(f"time step exceeds explicit limit {limit}")
        power = [gen for gen in generation]
        power[0] += inner_w
        power[-1] -= outer_w
        for i, g in enumerate(face_g):
            watts = g * (temperatures[i] - temperatures[i + 1])
            power[i] -= watts
            power[i + 1] += watts
        temperatures = [t + dt * p / c for t, p, c in zip(temperatures, power, capacity)]
        inner_j += dt * inner_w
        outer_j += dt * outer_w
        generated_j += dt * sum(generation)
        stored = sum(c * (t - t0) for c, t, t0 in zip(capacity, temperatures, initial))
        residual = energy_residual(stored, inner_j, outer_j, generated_j)
        record = {"time_s": (n + 1) * dt, "temperatures_c": temperatures[:],
                  "inner_j": inner_j, "outer_j": outer_j, "generated_j": generated_j,
                  "stored_j": stored, "residual_j": residual}
        if any(not math.isfinite(value) for value in [*temperatures, inner_j, outer_j, generated_j, stored, residual]):
            raise ValueError("nonfinite result")
        records.append(record)
    return {"records": records}
