"""Boundary variant with temperature-dependent k and schedule, no radiation."""

import math

from .geometry import centers


def conductivities(layers, temperatures):
    values = []
    for layer, temperature in zip(layers, temperatures, strict=True):
        value = layer["k0_w_m_k"] * (1 + layer["alpha_per_k"] * (temperature - 20))
        if not math.isfinite(value) or value <= 0:
            raise ValueError("conductivity is not positive")
        values.append(value)
    return values


def active_segment(schedule, time_s):
    selected = schedule[0]
    for segment in schedule[1:]:
        if segment["start_s"] > time_s:
            break
        selected = segment
    return selected


def boundary_powers(radii, length, temperatures, conductivities_now, segment):
    inner = segment["inner_flux_w_m2"] * 2 * math.pi * radii[0] * length
    h = segment["h_w_m2_k"]
    if h == 0:
        return inner, 0.0, 0.0
    outer = radii[-1]
    center = centers(radii)[-1]
    resistance = math.log(outer / center) / (2 * math.pi * length * conductivities_now[-1])
    resistance += 1 / (h * 2 * math.pi * outer * length)
    conductance = 1 / resistance
    return inner, conductance * (temperatures[-1] - segment["ambient_c"]), conductance
