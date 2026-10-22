"""Material law and imposed boundary conditions."""

import math

from .geometry import centers


def conductivities(layers, temperatures):
    return [layer["k0_w_m_k"] for layer in layers]


def active_segment(schedule, time_s):
    return schedule[0]


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
