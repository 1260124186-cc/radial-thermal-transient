"""Independent checks for the radial wall heat balance."""

import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


SIGMA = 5.670374419e-8

SOLVER_PATH = os.environ.get("RADIAL_HEAT_ENTRY", "/workspace/radial_heat/solver.py")


def case(radii=None, temperatures=None, alpha=0.0, schedule=None, dt=1.0, steps=3,
         length=1.3, q_gen=0.0):
    """Build a valid input case with the given geometry and boundary data."""
    radii = radii or [0.025, 0.04, 0.065]
    temperatures = temperatures or [75.0] * (len(radii) - 1)
    materials = [
        {"rho_kg_m3": 850 + 65 * i, "cp_j_kg_k": 980 + 90 * i,
         "k0_w_m_k": 0.35 + 0.08 * i, "alpha_per_k": alpha,
         "q_gen_w_m3": q_gen, "initial_c": temperatures[i]}
        for i in range(len(temperatures))
    ]
    return {"radii_m": radii, "length_m": length, "layers": materials,
            "schedule": schedule or [{"start_s": 0, "inner_flux_w_m2": 0.0,
                                      "ambient_c": 15.0, "h_w_m2_k": 12.0, "epsilon": 0.0}],
            "dt_s": dt, "steps": steps}


def reference(data):
    """Compute expected records from control-volume resistances and sources."""
    edges = data["radii_m"]
    length = data["length_m"]
    layers = data["layers"]
    midpoint = [(edges[i] + edges[i + 1]) * 0.5 for i in range(len(layers))]
    volume = [math.pi * (edges[i + 1] ** 2 - edges[i] ** 2) * length for i in range(len(layers))]
    heat_capacity = [layer["rho_kg_m3"] * layer["cp_j_kg_k"] * volume[i]
                     for i, layer in enumerate(layers)]
    generation = [layer["q_gen_w_m3"] * volume[i] for i, layer in enumerate(layers)]
    start = [layer["initial_c"] for layer in layers]
    temperature = start[:]
    total_in = total_out = total_gen = 0.0
    rows = [{"time_s": 0.0, "temperatures_c": start[:], "inner_j": 0.0,
             "outer_j": 0.0, "generated_j": 0.0, "stored_j": 0.0, "residual_j": 0.0}]
    for step in range(data["steps"]):
        time = step * data["dt_s"]
        boundary = max((s for s in data["schedule"] if s["start_s"] <= time),
                       key=lambda s: s["start_s"])
        k = [layer["k0_w_m_k"] * (1 + layer["alpha_per_k"] * (temperature[i] - 20))
             for i, layer in enumerate(layers)]
        watts = generation[:]
        inward = boundary["inner_flux_w_m2"] * 2 * math.pi * edges[0] * length
        watts[0] += inward
        for i in range(len(layers) - 1):
            left = math.log(edges[i + 1] / midpoint[i]) / (2 * math.pi * length * k[i])
            right = math.log(midpoint[i + 1] / edges[i + 1]) / (2 * math.pi * length * k[i + 1])
            g = 1 / (left + right)
            flow = (temperature[i] - temperature[i + 1]) * g
            watts[i] -= flow
            watts[i + 1] += flow
        area = 2 * math.pi * edges[-1] * length
        conv_g = 0.0
        q_conv = 0.0
        if boundary["h_w_m2_k"]:
            half = math.log(edges[-1] / midpoint[-1]) / (2 * math.pi * length * k[-1])
            film = 1 / (2 * math.pi * edges[-1] * length * boundary["h_w_m2_k"])
            conv_g = 1 / (half + film)
            q_conv = conv_g * (temperature[-1] - boundary["ambient_c"])
        q_rad = 0.0
        rad_g = 0.0
        if boundary["epsilon"] > 0:
            surface_k = temperature[-1] + 273.15
            ambient_k = boundary["ambient_c"] + 273.15
            q_rad = boundary["epsilon"] * SIGMA * area * (surface_k ** 4 - ambient_k ** 4)
            rad_g = boundary["epsilon"] * SIGMA * area * 4.0 * surface_k ** 3
        outward = q_conv + q_rad
        outer_g = conv_g + rad_g
        watts[-1] -= outward
        next_temp = [value + data["dt_s"] * watts[i] / heat_capacity[i]
                     for i, value in enumerate(temperature)]
        total_in += data["dt_s"] * inward
        total_out += data["dt_s"] * outward
        total_gen += data["dt_s"] * sum(generation)
        stored = sum(c * (now - before) for c, now, before in
                     zip(heat_capacity, next_temp, start, strict=True))
        temperature = next_temp
        rows.append({"time_s": (step + 1) * data["dt_s"], "temperatures_c": temperature[:],
                     "inner_j": total_in, "outer_j": total_out, "generated_j": total_gen,
                     "stored_j": stored, "residual_j": stored - total_in + total_out - total_gen})
    return rows


def _run(data, existing=None):
    """Run the CLI once and return exit code, payload text, and stderr."""
    with tempfile.TemporaryDirectory() as temp:
        source = Path(temp) / "case.json"
        output = Path(temp) / "result.json"
        source.write_text(json.dumps(data), encoding="utf-8")
        if existing is not None:
            output.write_text(existing, encoding="utf-8")
        completed = subprocess.run([sys.executable, "-m", "radial_heat", str(source), str(output)],
                                   cwd="/workspace", capture_output=True, text=True, timeout=20)
        payload = output.read_text(encoding="utf-8") if output.exists() else None
        return completed.returncode, payload, completed.stderr


def _rows(data):
    """Return parsed records when the CLI succeeds, otherwise None."""
    status, payload, _stderr = _run(data)
    if status != 0 or payload is None:
        return None
    return json.loads(payload)["records"]


def _matches(actual, expected, ledger_keys):
    """Return whether two record lists match for temperature and ledger fields."""
    if actual is None or len(actual) != len(expected):
        return False
    for got, want in zip(actual, expected, strict=True):
        if not math.isclose(got.get("time_s"), want["time_s"], rel_tol=1e-9, abs_tol=1e-9):
            return False
        got_temp = got.get("temperatures_c")
        want_temp = want["temperatures_c"]
        if got_temp is None or len(got_temp) != len(want_temp):
            return False
        if not all(math.isclose(g, w, rel_tol=1e-9, abs_tol=1e-9)
                   for g, w in zip(got_temp, want_temp, strict=True)):
            return False
        for key in ledger_keys:
            if key not in got or key not in want:
                return False
            if not math.isclose(float(got[key]), float(want[key]), rel_tol=1e-9, abs_tol=1e-7):
                return False
    return True


LEDGER = ("inner_j", "outer_j", "generated_j", "stored_j", "residual_j")


def test_c1_two_layer_radial_flow():
    """Match a two-layer radial temperature history."""
    data = case(temperatures=[95, 30], steps=4)
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_c1_irregular_cells_and_length():
    """Match nonuniform cells with a longer pipe segment."""
    data = case(radii=[0.018, 0.019, 0.08, 0.095],
                temperatures=[100, 48, 22], steps=5, length=2.7)
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_c1_heterogeneous_interface():
    """Match an interface where adjacent layers have different conductivities."""
    data = case(radii=[0.02, 0.028, 0.042, 0.067], temperatures=[90, 50, 20])
    data["layers"][1]["k0_w_m_k"] = 0.025
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_c1_uniform_insulated_state():
    """Keep an insulated uniform-temperature wall unchanged."""
    data = case(temperatures=[35, 35], steps=3)
    data["schedule"][0].update({"ambient_c": 35, "h_w_m2_k": 0})
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_c2_temperature_dependent_conductivity():
    """Evaluate conductivity at the current cell temperature."""
    data = case(radii=[0.03, 0.07], temperatures=[90], alpha=0.03, steps=5)
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_c2_schedule_at_exact_switch():
    """Apply the new boundary segment exactly at its start time."""
    data = case(radii=[0.03, 0.07], temperatures=[70], steps=5, dt=2)
    data["schedule"].append({"start_s": 4, "inner_flux_w_m2": -180,
                             "ambient_c": 5, "h_w_m2_k": 25, "epsilon": 0.0})
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_c2_inner_surface_area():
    """Convert inner flux density using the inner cylindrical area."""
    data = case(radii=[0.02, 0.06], temperatures=[40], length=3, steps=2)
    data["schedule"][0].update({"inner_flux_w_m2": 750, "h_w_m2_k": 0})
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_c2_outer_half_cell_and_film():
    """Series-connect the outer half cell and convective film."""
    data = case(radii=[0.01, 0.1], temperatures=[65], steps=3)
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_c3_energy_ledger():
    """Keep the heat ledger consistent with storage change."""
    data = case(radii=[0.02, 0.07], temperatures=[40], steps=4)
    data["schedule"][0].update({"inner_flux_w_m2": 1000, "h_w_m2_k": 0})
    ok = _matches(_rows(data), reference(data), LEDGER)
    assert ok


def test_c3_exact_stability_boundary():
    """Accept a time step exactly equal to the stability limit."""
    data = case(radii=[0.03, 0.07], temperatures=[70], steps=1)
    radius, outer = data["radii_m"]
    length = data["length_m"]
    layer = data["layers"][0]
    c = layer["rho_kg_m3"] * layer["cp_j_kg_k"] * math.pi * (outer**2 - radius**2) * length
    g = 1 / (math.log(outer / ((radius + outer) / 2)) / (2 * math.pi * length * layer["k0_w_m_k"])
             + 1 / (data["schedule"][0]["h_w_m2_k"] * 2 * math.pi * outer * length))
    data["dt_s"] = c / g
    rows = _rows(data)
    assert rows is not None and len(rows) == 2


def test_c3_unstable_step_has_no_artifact():
    """Reject an unstable time step without leaving an output file."""
    data = case(radii=[0.03, 0.07], temperatures=[70], dt=1e9, steps=1)
    status, payload, _stderr = _run(data)
    assert status != 0 and payload is None


def test_c3_invalid_inputs_do_not_replace_artifact():
    """Reject invalid inputs without overwriting an existing artifact."""
    invalid = [
        {"radii_m": [0.03, 0.03]},
        {"layers": [{"rho_kg_m3": 850, "cp_j_kg_k": 980, "k0_w_m_k": -1,
                     "alpha_per_k": 0, "q_gen_w_m3": 0, "initial_c": 40}]},
        {"schedule": [{"start_s": 2, "inner_flux_w_m2": 0, "ambient_c": 10,
                       "h_w_m2_k": 5, "epsilon": 0.0}]},
        {"schedule": [{"start_s": 0, "inner_flux_w_m2": 0, "ambient_c": 10,
                       "h_w_m2_k": 5, "epsilon": 1.5}]},
    ]
    outcomes = []
    for change in invalid:
        data = case(radii=[0.03, 0.07], temperatures=[40])
        data.update(change)
        status, payload, _stderr = _run(data, existing="previous valid result")
        outcomes.append(status != 0 and payload == "previous valid result")
    assert all(outcomes)


def test_c4_generation_heats_insulated_cell():
    """Heat an insulated cell by its volumetric source."""
    data = case(radii=[0.03, 0.07], temperatures=[40], steps=4, q_gen=5000)
    data["schedule"][0].update({"inner_flux_w_m2": 0, "h_w_m2_k": 0})
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_c4_generated_ledger_and_residual():
    """Include generated heat in the ledger and keep the residual near zero."""
    data = case(radii=[0.03, 0.07], temperatures=[40], steps=4, q_gen=2000)
    data["schedule"][0].update({"inner_flux_w_m2": 0, "h_w_m2_k": 0})
    ok = _matches(_rows(data), reference(data), LEDGER)
    assert ok


def test_c4_negative_generation_sink():
    """Treat a negative source as a heat sink that lowers temperature."""
    data = case(radii=[0.03, 0.07], temperatures=[60], steps=4, q_gen=-3000)
    data["schedule"][0].update({"inner_flux_w_m2": 0, "h_w_m2_k": 0})
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_c4_generation_not_in_stability_limit():
    """Exclude the source term from the explicit stability limit."""
    data = case(radii=[0.03, 0.07], temperatures=[70], steps=1, q_gen=1e6)
    radius, outer = data["radii_m"]
    length = data["length_m"]
    layer = data["layers"][0]
    c = layer["rho_kg_m3"] * layer["cp_j_kg_k"] * math.pi * (outer**2 - radius**2) * length
    g = 1 / (math.log(outer / ((radius + outer) / 2)) / (2 * math.pi * length * layer["k0_w_m_k"])
             + 1 / (data["schedule"][0]["h_w_m2_k"] * 2 * math.pi * outer * length))
    data["dt_s"] = c / g
    rows = _rows(data)
    assert rows is not None and len(rows) == 2


def test_c5_radiation_cools_insulated_surface():
    """Lose heat from an insulated surface through radiation alone."""
    data = case(radii=[0.03, 0.07], temperatures=[120], steps=4)
    data["schedule"][0].update({"inner_flux_w_m2": 0, "h_w_m2_k": 0, "epsilon": 0.9})
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_c5_radiation_and_convection_combine():
    """Combine convection and radiation at the outer surface."""
    data = case(radii=[0.03, 0.07], temperatures=[90], steps=3)
    data["schedule"][0].update({"h_w_m2_k": 10, "epsilon": 0.8})
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_c5_radiation_kelvin_scale():
    """Evaluate the T^4 radiation term on the Kelvin scale."""
    data = case(radii=[0.03, 0.07], temperatures=[200], steps=4)
    data["schedule"][0].update({"inner_flux_w_m2": 0, "h_w_m2_k": 0, "epsilon": 0.9})
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_e2e_multilayer_non_linear_schedule_and_ledger():
    """Match a full multi-layer nonlinear case with a scheduled source."""
    data = case(radii=[0.018, 0.025, 0.04, 0.07], temperatures=[95, 75, 45],
                alpha=0.008, steps=7, dt=3, length=1.8, q_gen=1500)
    data["layers"][1]["q_gen_w_m3"] = 0
    data["schedule"].append({"start_s": 9, "inner_flux_w_m2": -60,
                             "ambient_c": 6, "h_w_m2_k": 22, "epsilon": 0.9})
    ok = _matches(_rows(data), reference(data), LEDGER)
    assert ok
