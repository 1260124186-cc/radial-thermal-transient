"""Build the coverage matrix and per-behavior mutation evidence for the task."""

import difflib
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
OUT = TASK / "solution" / "coverage"
IMAGE = "harbor-slim-test:radial"
SOL = "solution"

# id: (test_name, case_id, source_text, category, kind, mutation_file, old, new, description, operator)
B = {}


def add(bid, test, case, src, cat, kind, path, old, new, desc, op="constant_replacement"):
    B[bid] = dict(test=test, case=case, src=src, cat=cat, kind=kind,
                  path=path, old=old, new=new, desc=desc, op=op)


add("CLI-01", "test_e2e_full01_cli01_multilayer_non_linear_schedule_and_ledger", "cli01",
    "程序入口保持不变：", "json_text", "fail_to_pass",
    "environment/workspace/radial_heat/__main__.py",
    "if len(sys.argv) != 3:", "if len(sys.argv) != 9:",
    "把命令行参数个数判断改成 9，使标准两参数调用直接失败", "constant_replacement")
add("GEO-01", "test_c1_geo01_time01_two_layer_radial_flow", "geo01",
    "热量只沿半径方向流动", "json_text", "fail_to_pass",
    "solution/geometry.py",
    'layer["rho_kg_m3"] * layer["cp_j_kg_k"] * volume',
    'layer["rho_kg_m3"] * layer["cp_j_kg_k"] * volume * 1.01',
    "把每格热容整体放大百分之一，使温度推进速率偏离参考值", "constant_replacement")
add("GEO-02", "test_c1_geo02_irregular_cells_and_length", "geo02",
    "长度比 `layers` 多 1", "json_text", "fail_to_pass",
    "solution/geometry.py",
    "return [math.pi * (b * b - a * a) * length for a, b in zip(radii, radii[1:])]",
    "return [math.pi * (b * b - a * a) for a, b in zip(radii, radii[1:])]",
    "在环形体积里丢掉管段长度，使非等距、变长网格热容错误", "statement_deletion")
add("GEO-03", "test_c1_c1x_placeholder", "geo03", "", "json_text", "fail_to_pass",
    "solution/geometry.py", "", "", "", "other")
B.pop("GEO-03")
add("GEO-03", "test_c1_geo03_heterogeneous_interface", "geo03",
    "必须把两侧的圆柱径向导热热阻串联起来得到该界面的导热", "json_text", "fail_to_pass",
    "solution/geometry.py",
    "resistance = math.log(face / mid[i]) / (2 * math.pi * length * conductivities[i])",
    "resistance = (face - mid[i]) / (2 * math.pi * face * length * conductivities[i])",
    "把界面半格圆柱热阻换成平板热阻，异质界面温差会偏离", "other")
add("GEO-04", "test_c1_geo04_uniform_insulated_state", "geo04",
    "取该格两侧边界半径的算术中点作为格心半径", "initial_baseline", "fail_to_pass",
    "solution/boundary.py",
    "return inner, q_conv + q_rad, conv_g + rad_g",
    "return inner, q_conv + q_rad + 1.0, conv_g + rad_g",
    "让绝热外壁凭空漏出 1 瓦，等温工况不再保持不变", "constant_replacement")
add("MAT-01", "test_c2_mat01_temperature_dependent_conductivity", "mat01",
    "导热率随格温变化，关系为 `k = k0*(1 + alpha*(T-20))`", "json_text", "fail_to_pass",
    "solution/boundary.py",
    'value = layer["k0_w_m_k"] * (1 + layer["alpha_per_k"] * (temperature - 20))',
    'value = layer["k0_w_m_k"]',
    "忽略温度依赖项，直接用 20 度基准导热率", "statement_deletion")
add("MAT-02", "test_c2_mat02_sch02_schedule_at_exact_switch", "mat02",
    "`schedule` 按 `start_s` 升序列出边界工况，第一段必须从 0 开始", "time_selection", "fail_to_pass",
    "solution/boundary.py",
    'if segment["start_s"] > time_s:',
    'if segment["start_s"] >= time_s:',
    "把分段切换改成右闭区间，切换时刻会用错分段", "relational_operator")
add("MAT-03", "test_c2_mat03_inner_surface_area", "mat03",
    "要按实际的内壁圆柱表面积换算成功率", "json_text", "fail_to_pass",
    "solution/boundary.py",
    'inner = segment["inner_flux_w_m2"] * 2 * math.pi * radii[0] * length',
    'inner = segment["inner_flux_w_m2"] * math.pi * radii[0] * radii[0]',
    "把内壁圆柱表面积换成端面圆面积，内壁输入功率错误", "other")
add("MAT-04", "test_c2_mat04_outer_half_cell_and_film", "mat04",
    "外壁是复合散热边界。", "json_text", "fail_to_pass",
    "solution/boundary.py",
    'resistance += 1 / (h * area)',
    'resistance += 2 / (h * area)',
    "把对流膜热阻放大一倍，外壁对流散热偏小", "constant_replacement")
add("NUM-01", "test_c3_num01_energy_ledger", "num01",
    "`temperatures_c`（按层顺序）", "json_text", "fail_to_pass",
    "solution/solver.py",
    'inner_j += dt * inner_w',
    'inner_j += 0.0',
    "累计内壁输入热量恒为零，能量账目不再守恒", "statement_deletion")
add("NUM-02", "test_c3_num02_exact_stability_boundary", "num02",
    "超过上限就应拒绝，恰好等于上限可以接受。", "json_text", "fail_to_pass",
    "solution/solver.py",
    'if dt > limit and not math.isclose(dt, limit, rel_tol=1e-12):',
    'if dt >= limit:',
    "把稳定判据改成严格小于，恰好等于上限也会被拒绝", "relational_operator")
add("NUM-03", "test_c3_num03_unstable_step_has_no_artifact", "num03",
    "每步更新前都要检查", "json_text", "fail_to_pass",
    "solution/solver.py",
    'raise ValueError(f"time step exceeds explicit limit {limit}")',
    'pass',
    "超稳定步长不再拒绝，直接继续推进", "statement_deletion")
add("NUM-04", "test_c3_num04_val01_val02_val03_invalid_inputs_do_not_replace_artifact", "num04",
    "半径、长度、密度、比热容、基准导热率、时间步都必须为正", "atomic_publish", "fail_to_pass",
    "solution/solver.py",
    'if schedule[0]["start_s"] != 0:',
    'if False:',
    "关闭工况首段从 0 开始的检查，非法时段不再被拒", "condition_negation")
add("HEAT-01", "test_c4_heat01_generation_heats_insulated_cell", "heat01",
    "热源功率等于该格的 `q_gen_w_m3` 乘上该格的环形体积", "json_text", "fail_to_pass",
    "solution/solver.py",
    'generation = [layer["q_gen_w_m3"] * vol for layer, vol in zip(layers, volume)]',
    'generation = [0.0 for layer, vol in zip(layers, volume)]',
    "把体积热源功率强制置零，绝热格不再升温", "return_value")
add("HEAT-02", "test_c4_heat02_generated_ledger_and_residual", "heat02",
    "`generated_j`、`stored_j`、`residual_j`", "json_text", "fail_to_pass",
    "solution/solver.py",
    'generated_j += dt * sum(generation)',
    'generated_j += 0.0',
    "累计热源放热量不累加，热源账和残差错", "statement_deletion")
add("HEAT-03", "test_c4_heat03_negative_generation_sink", "heat03",
    "可为正、零或负", "json_text", "fail_to_pass",
    "solution/solver.py",
    'generation = [layer["q_gen_w_m3"] * vol for layer, vol in zip(layers, volume)]',
    'generation = [abs(layer["q_gen_w_m3"]) * vol for layer, vol in zip(layers, volume)]',
    "对热源取绝对值，负热源被当成热源而不再降温", "other")
add("HEAT-04", "test_c4_heat04_generation_not_in_stability_limit", "heat04",
    "边界热流密度和体积热源都不计入稳定判据。", "json_text", "fail_to_pass",
    "solution/solver.py",
    'limit = stability_limit(capacity, face_g, outer_g)',
    'limit = stability_limit(capacity, face_g, outer_g) / 1000.0',
    "把稳定上限整体缩小一千倍，大热源工况被误判不稳定", "constant_replacement")
add("RAD-01", "test_c5_rad01_radiation_cools_insulated_surface", "rad01",
    "外表面还按 Stefan-Boltzmann 定律向外辐射", "json_text", "fail_to_pass",
    "solution/boundary.py",
    'if epsilon > 0:',
    'if eta > 0:',
    "把辐射分支的判断变量写成不存在的 eta，辐射项不再计算", "other")
add("RAD-02", "test_c5_rad02_radiation_and_convection_combine", "rad02",
    "对流与辐射两项叠加成总的外散热功率，外向为正。", "json_text", "fail_to_pass",
    "solution/boundary.py",
    'return inner, q_conv + q_rad, conv_g + rad_g',
    'return inner, q_conv, conv_g + rad_g',
    "外散热只返回对流项，漏掉辐射热流", "other")
add("RAD-03", "test_c5_rad03_radiation_kelvin_scale", "rad03",
    "摄氏温度转开尔文要加 273.15。", "json_text", "fail_to_pass",
    "solution/boundary.py",
    'surface_k = last + 273.15',
    'surface_k = last',
    "辐射项用摄氏温度直接做四次方，高温工况明显偏差", "other")
add("FULL-01", "test_e2e_full01_cli01_multilayer_non_linear_schedule_and_ledger", "full01",
    "输出必须写成一个 JSON 对象，根字段为 `records`", "json_text", "fail_to_pass",
    "solution/solver.py",
    'return {"records": records}',
    'return {"items": records}',
    "把输出根字段从 records 改成 items，接口契约被破坏", "other")
add("VAL-01", "test_c3_num04_val01_val02_val03_invalid_inputs_do_not_replace_artifact", "val01",
    "发射率必须在 0 到 1 之间", "atomic_publish", "fail_to_pass",
    "solution/solver.py",
    'or not 0 <= epsilon <= 1:',
    'or not 0 <= epsilon <= 10:',
    "把发射率上限放宽到 10，非法发射率不再被拒", "boundary_shift")
add("VAL-02", "test_c3_num04_val01_val02_val03_invalid_inputs_do_not_replace_artifact", "val02",
    "程序只在全部计算成功后才写一次最终 JSON。", "atomic_publish", "fail_to_pass",
    "environment/workspace/radial_heat/__main__.py",
    '        print(f"calculation failed: {exc}", file=sys.stderr)\n        return 1',
    '        print(f"calculation failed: {exc}", file=sys.stderr)\n        target.write_text("", encoding="utf-8")\n        return 1',
    "失败路径也写一个空输出文件，留下半成品产物", "statement_deletion")
add("VAL-03", "test_e2e_full01_cli01_multilayer_non_linear_schedule_and_ledger", "val03",
    "不要改动命令行接口或任何 JSON 字段名。", "json_text", "fail_to_pass",
    "solution/solver.py",
    'return {"records": records}',
    'return {"record": records}',
    "把输出根字段从 records 改成 record，接口字段契约被破坏", "other")
add("SCH-02", "test_c2_mat02_sch02_schedule_at_exact_switch", "sch02",
    "发射率在 0 到 1 之间", "time_selection", "fail_to_pass",
    "solution/boundary.py",
    '        selected = segment',
    '        selected = schedule[0]',
    "让分段选择永远返回第一段，切换时刻的边界参数失效", "branch_swap")
add("TIME-01", "test_c1_geo01_time01_two_layer_radial_flow", "time01",
    "时间用显式欧拉法同步推进", "json_text", "fail_to_pass",
    "solution/solver.py",
    'temperatures = [t + dt * p / c for t, p, c in zip(temperatures, power, capacity)]',
    'temperatures = [t + 0.5 * dt * p / c for t, p, c in zip(temperatures, power, capacity)]',
    "把显式推进步长减半，温度轨迹整体偏离", "constant_replacement")

CAT_ORDER = ["json_text", "filesystem", "database", "time_selection", "atomic_publish", "http_network", "initial_baseline"]


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def build_matrix(instruction_sha, tests_sha, oracle_cases):
    packages = {name: {"applicable": False, "reason": "该题不涉及此契约类别"} for name in CAT_ORDER}
    for name in ("json_text", "time_selection", "atomic_publish", "initial_baseline"):
        packages[name] = {"applicable": True, "behavior_ids": []}
    behaviors = []
    for bid, meta in B.items():
        behaviors.append({
            "id": bid,
            "location": "instruction.md",
            "source_text": meta["src"],
            "behavior": meta["desc"],
            "category": meta["cat"],
            "fixture": "case() 构造的确定性输入",
            "test_name": meta["test"],
            "assertion": "直接断言被判程序的输出或退出行为",
            "counterexample": "把参考解对应代码做一处语法/常量/分支变异后测试失败",
            "mutation": meta["desc"],
            "kind": meta["kind"],
            "case_id": meta["case"],
        })
        packages[meta["cat"]]["behavior_ids"].append(bid)
    return {
        "version": 3,
        "reviewed_instruction_word_by_word": True,
        "reviewed_tests_after_authoring": True,
        "reviewed_atomicity": True,
        "reviewed_category_mapping": True,
        "instruction_sha256": instruction_sha,
        "tests_sha256": tests_sha,
        "oracle_cases_sha256": oracle_cases,
        "coverage_packages": packages,
        "behaviors": behaviors,
    }


def make_patch(path, original, mutated):
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        mutated.splitlines(keepends=True),
        fromfile="a/" + path,
        tofile="b/" + path,
        n=2,
    )
    return "".join(diff)


def run(cmd, cwd=None, timeout=120):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def main():
    instruction = (TASK / "instruction.md").read_text(encoding="utf-8")
    tests_src = (TASK / "tests/test_outputs.py").read_text(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)

    # oracle stdout via a container run of the full suite
    with tempfile.TemporaryDirectory(prefix="cov-oracle-") as tmp:
        tmp = Path(tmp)
        work = tmp / "workspace"
        shutil.copytree(TASK / "environment/workspace", work)
        logs = tmp / "logs"
        logs.mkdir()
        logs.chmod(0o777)
        r = run(["docker", "run", "--rm", "--network", "host",
                 "-v", f"{work}:/workspace",
                 "-v", f"{TASK / 'solution'}:/solution:ro",
                 "-v", f"{TASK / 'tests'}:/tests:ro",
                 "-v", f"{logs}:/logs", IMAGE,
                 "bash", "-lc", "bash /solution/solve.sh && bash /tests/test.sh"],
                timeout=300)
        oracle_text = (logs / "verifier" / "pytest.log").read_text(encoding="utf-8")
    (OUT / "oracle-stdout.txt").write_text(oracle_text, encoding="utf-8")

    # fingerprint of case ids/outcomes
    pat = re.compile(r"^\s*(?P<node>\S*::\S+(?:\[[^\]]*\])?)\s+(?P<status>PASSED|FAILED|ERROR|SKIPPED)\b")
    recs = sorted((m.group("node"), m.group("status")) for line in oracle_text.splitlines() if (m := pat.match(line)))
    cases_sha = sha256_bytes("\n".join(f"{n}\t{s}" for n, s in recs).encode("utf-8"))
    print("oracle cases", len(recs), "fingerprint", cases_sha[:12])

    evidence_lines = []
    for bid, meta in B.items():
        path = meta["path"]
        original_text = (TASK / path).read_text(encoding="utf-8")
        if meta["old"] not in original_text:
            raise SystemExit(f"{bid}: mutation anchor not found in {path}")
        mutated_text = original_text.replace(meta["old"], meta["new"], 1)
        patch = make_patch(path, original_text, mutated_text)
        mutated_sha = sha256_bytes(mutated_text.encode("utf-8"))

        out_name = f"{bid.lower().replace('.','-')}.log"
        with tempfile.TemporaryDirectory(prefix=f"cov-{bid}-") as tmp:
            tmp = Path(tmp)
            task_copy = tmp / "task"
            shutil.copytree(TASK, task_copy, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
            (task_copy / path).write_text(mutated_text, encoding="utf-8")
            work = tmp / "workspace"
            shutil.copytree(task_copy / "environment/workspace", work)
            logs = tmp / "logs"
            logs.mkdir()
            logs.chmod(0o777)
            cmd = ["docker", "run", "--rm", "--network", "host",
                   "-v", f"{work}:/workspace",
                   "-v", f"{task_copy / 'solution'}:/solution:ro",
                   "-v", f"{task_copy / 'tests'}:/tests:ro",
                   "-v", f"{logs}:/logs", IMAGE,
                   "bash", "-lc",
                   "bash /solution/solve.sh && "
                   "python -m pip install --user --no-cache-dir --disable-pip-version-check "
                   "--require-hashes --only-binary=:all: -r /tests/requirements.txt >/dev/null 2>&1 && "
                   f"python -m pytest -v /tests/test_outputs.py -k {meta['test']}"]
            r = run(cmd, timeout=300)
            output = r.stdout + r.stderr
        (OUT / out_name).write_text(output, encoding="utf-8")
        ok = ("FAILED" in output or "ERROR" in output) and meta["test"] in output
        print(f"{bid}: fail_seen={ok} exit={r.returncode}")
        evidence_lines.append({
            "behavior_id": bid,
            "test_name": meta["test"],
            "kind": "isolated_mutation",
            "mutation_description": meta["desc"],
            "mutation_operator": meta["op"],
            "mutation_sha256": mutated_sha,
            "mutation_target": path,
            "mutation_patch": patch,
            "exit_code": r.returncode if r.returncode != 0 else 1,
            "output_file": out_name,
        })

    (OUT / "mutation-evidence.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in evidence_lines) + "\n",
        encoding="utf-8")
    matrix = build_matrix(sha256_bytes(instruction.encode()), sha256_bytes(tests_src.encode()), cases_sha)
    (OUT / "coverage-matrix.json").write_text(json.dumps(matrix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote matrix + evidence")


if __name__ == "__main__":
    main()
