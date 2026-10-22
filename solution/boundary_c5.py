"""Boundary variant with radiation, but constant conductivity and first segment."""

import math

from .geometry import centers

SIGMA = 5.670374419e-8


def conductivities(layers, temperatures):
    return [layer["k0_w_m_k"] for layer in layers]


def active_segment(schedule, time_s):
    return schedule[0]


def boundary_powers(radii, length, temperatures, conductivities_now, segment):
    inner = segment["inner_flux_w_m2"] * 2 * math.pi * radii[0] * length
    outer = radii[-1]
    center = centers(radii)[-1]
    area = 2 * math.pi * outer * length
    ambient = segment["ambient_c"]
    last = temperatures[-1]

    h = segment["h_w_m2_k"]
    conv_g = 0.0
    q_conv = 0.0
    if h > 0:
        resistance = math.log(outer / center) / (2 * math.pi * length * conductivities_now[-1])
        resistance += 1 / (h * area)
        conv_g = 1 / resistance
        q_conv = conv_g * (last - ambient)

    epsilon = segment["epsilon"]
    rad_g = 0.0
    q_rad = 0.0
    if epsilon > 0:
        surface_k = last + 273.15
        ambient_k = ambient + 273.15
        q_rad = epsilon * SIGMA * area * (surface_k ** 4 - ambient_k ** 4)
        rad_g = epsilon * SIGMA * area * 4.0 * surface_k ** 3

    return inner, q_conv + q_rad, conv_g + rad_g
