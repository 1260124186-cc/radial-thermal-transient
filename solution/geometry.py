"""Pipe-wall geometry and conductive coupling."""

import math


def centers(radii):
    return [(a + b) / 2 for a, b in zip(radii, radii[1:])]


def volumes(radii, length):
    return [math.pi * (b * b - a * a) * length for a, b in zip(radii, radii[1:])]


def capacities(radii, length, layers):
    return [
        layer["rho_kg_m3"] * layer["cp_j_kg_k"] * volume
        for volume, layer in zip(volumes(radii, length), layers)
    ]


def face_conductances(radii, length, conductivities):
    mid = centers(radii)
    values = []
    for i in range(len(conductivities) - 1):
        face = radii[i + 1]
        resistance = math.log(face / mid[i]) / (2 * math.pi * length * conductivities[i])
        resistance += math.log(mid[i + 1] / face) / (2 * math.pi * length * conductivities[i + 1])
        values.append(1 / resistance)
    return values
