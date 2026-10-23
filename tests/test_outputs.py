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


def test_c1_geo01_time01_two_layer_radial_flow():
    """按题面「每格的能量存储用该环形控制体的真实体积和密度、比热来算」核对双层管温度历程。"""
    # case time01: explicit Euler synchronous time stepping
    data = case(temperatures=[95, 30], steps=4)
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_c1_geo02_irregular_cells_and_length():
    """按题面「length_m 是管段轴向长度」核对非等距、变长管段的温度历程。"""
    data = case(radii=[0.018, 0.019, 0.08, 0.095],
                temperatures=[100, 48, 22], steps=5, length=2.7)
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_c1_geo03_heterogeneous_interface():
    """按题面「必须把两侧的圆柱径向导热热阻串联起来得到该界面的导热」核对异质界面。"""
    data = case(radii=[0.02, 0.028, 0.042, 0.067], temperatures=[90, 50, 20])
    data["layers"][1]["k0_w_m_k"] = 0.025
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_c1_geo04_uniform_insulated_state():
    """按题面「取该格两侧边界半径的算术中点作为格心半径」核对等温绝热状态。"""
    data = case(temperatures=[35, 35], steps=3)
    data["schedule"][0].update({"ambient_c": 35, "h_w_m2_k": 0})
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_c2_mat01_temperature_dependent_conductivity():
    """按题面「导热率随格温变化，关系为 k = k0*(1 + alpha*(T-20))」核对温度依赖导热率。"""
    data = case(radii=[0.03, 0.07], temperatures=[90], alpha=0.03, steps=5)
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_c2_mat02_sch02_schedule_at_exact_switch():
    """按题面「schedule 按 start_s 升序，第一段必须从 0 开始」核对切换时刻的边界取值。"""
    # case sch02: emissivity range in the schedule segment
    data = case(radii=[0.03, 0.07], temperatures=[70], steps=5, dt=2)
    data["schedule"].append({"start_s": 4, "inner_flux_w_m2": -180,
                             "ambient_c": 5, "h_w_m2_k": 25, "epsilon": 0.0})
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_c2_mat03_inner_surface_area():
    """按题面「内壁热流密度要按实际的内壁圆柱表面积换算成功率」核对内壁输入。"""
    data = case(radii=[0.02, 0.06], temperatures=[40], length=3, steps=2)
    data["schedule"][0].update({"inner_flux_w_m2": 750, "h_w_m2_k": 0})
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_c2_mat04_outer_half_cell_and_film():
    """按题面「最外层格心到管外表面有一段圆柱导热，这段导热与外表面的对流换热串联」核对对流边界。"""
    data = case(radii=[0.01, 0.1], temperatures=[65], steps=3)
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_c3_num01_energy_ledger():
    """按题面「inner_j 和 outer_j 是从 0 开始累计的内壁输入热量和外壁散热量」核对能量账。"""
    data = case(radii=[0.02, 0.07], temperatures=[40], steps=4)
    data["schedule"][0].update({"inner_flux_w_m2": 1000, "h_w_m2_k": 0})
    ok = _matches(_rows(data), reference(data), LEDGER)
    assert ok


def test_c3_num02_exact_stability_boundary():
    """按题面「超过上限就应拒绝，恰好等于上限可以接受」核对显式稳定边界。"""
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


def test_c3_num03_unstable_step_has_no_artifact():
    """按题面「超过上限就应拒绝」核对超稳定步长被拒且不留产物。"""
    data = case(radii=[0.03, 0.07], temperatures=[70], dt=1e9, steps=1)
    status, payload, _stderr = _run(data)
    assert status != 0 and payload is None


def test_c3_num04_val01_val02_val03_invalid_inputs_do_not_replace_artifact():
    """按题面「不能留下输出文件，也不能覆盖已存在的输出文件」核对非法输入拒收。"""
    # cases val01 val02 val03: emissivity range, atomic single write, stable CLI contract
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


def test_c4_heat01_generation_heats_insulated_cell():
    """按题面「热源功率等于该格的 q_gen_w_m3 乘上该格的环形体积」核对绝热格升温。"""
    data = case(radii=[0.03, 0.07], temperatures=[40], steps=4, q_gen=5000)
    data["schedule"][0].update({"inner_flux_w_m2": 0, "h_w_m2_k": 0})
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_c4_heat02_generated_ledger_and_residual():
    """按题面「generated_j 是累计的热源放热量」核对热源账与残差。"""
    data = case(radii=[0.03, 0.07], temperatures=[40], steps=4, q_gen=2000)
    data["schedule"][0].update({"inner_flux_w_m2": 0, "h_w_m2_k": 0})
    ok = _matches(_rows(data), reference(data), LEDGER)
    assert ok


def test_c4_heat03_negative_generation_sink():
    """按题面「q_gen_w_m3 可为正、零或负」核对负热源使温度下降。"""
    data = case(radii=[0.03, 0.07], temperatures=[60], steps=4, q_gen=-3000)
    data["schedule"][0].update({"inner_flux_w_m2": 0, "h_w_m2_k": 0})
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_c4_heat04_generation_not_in_stability_limit():
    """按题面「边界热流密度和体积热源都不计入稳定判据」核对热源不影响稳定上限。"""
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


def test_c5_rad01_radiation_cools_insulated_surface():
    """按题面「外表面还按 Stefan-Boltzmann 定律向外辐射」核对纯辐射散热。"""
    data = case(radii=[0.03, 0.07], temperatures=[120], steps=4)
    data["schedule"][0].update({"inner_flux_w_m2": 0, "h_w_m2_k": 0, "epsilon": 0.9})
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_c5_rad02_radiation_and_convection_combine():
    """按题面「对流与辐射两项叠加成总的外散热功率」核对复合散热。"""
    data = case(radii=[0.03, 0.07], temperatures=[90], steps=3)
    data["schedule"][0].update({"h_w_m2_k": 10, "epsilon": 0.8})
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_c5_rad03_radiation_kelvin_scale():
    """按题面「摄氏温度转开尔文要加 273.15」核对高温辐射项。"""
    data = case(radii=[0.03, 0.07], temperatures=[200], steps=4)
    data["schedule"][0].update({"inner_flux_w_m2": 0, "h_w_m2_k": 0, "epsilon": 0.9})
    ok = _matches(_rows(data), reference(data), ())
    assert ok


def test_e2e_full01_cli01_multilayer_non_linear_schedule_and_ledger():
    """按题面「输出必须写成一个 JSON 对象，根字段为 records」核对综合工况的完整账目。"""
    # cases cli01 val03: stable command line entry point and records field name
    data = case(radii=[0.018, 0.025, 0.04, 0.07], temperatures=[95, 75, 45],
                alpha=0.008, steps=7, dt=3, length=1.8, q_gen=1500)
    data["layers"][1]["q_gen_w_m3"] = 0
    data["schedule"].append({"start_s": 9, "inner_flux_w_m2": -60,
                             "ambient_c": 6, "h_w_m2_k": 22, "epsilon": 0.9})
    ok = _matches(_rows(data), reference(data), LEDGER)
    assert ok
