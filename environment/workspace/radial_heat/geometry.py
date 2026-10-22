"""Pipe-wall geometry and conductive coupling."""

import math


def centers(radii):
    return [(a + b) / 2 for a, b in zip(radii, radii[1:])]


def capacities(radii, length, layers):
    return [
        layer["rho_kg_m3"] * layer["cp_j_kg_k"] * math.pi * (b * b - a * a) * length
        for a, b, layer in zip(radii, radii[1:], layers)
    ]


def face_conductances(radii, length, conductivities):
    # An equivalent flat section is used at each interface.
    mid = centers(radii)
    values = []
    for i in range(len(conductivities) - 1):
        face = radii[i + 1]
        area = 2 * math.pi * face * length
        resistance = (face - mid[i]) / (area * conductivities[i])
        resistance += (mid[i + 1] - face) / (area * conductivities[i + 1])
        values.append(1 / resistance)
    return values
