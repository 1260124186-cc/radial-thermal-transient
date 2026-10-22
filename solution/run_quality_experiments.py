"""Run the specified one-fix and bypass specimens through the real test script."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path


TASK = Path(__file__).resolve().parents[1]
IMAGE = "harbor-quality:radial-thermal-transient"
GROUPS = ("c1", "c2", "c3", "c4", "c5", "e2e")


def run_command(args, **kwargs):
    return subprocess.run(args, text=True, capture_output=True, check=False, **kwargs)


def copy_file(task_source, work_dest):
    shutil.copy2(TASK / "solution" / task_source, work_dest)


def specimen(root, label, files, override=None):
    work = root / label / "workspace"
    shutil.copytree(TASK / "environment" / "workspace", work)
    for entry in files:
        if isinstance(entry, tuple):
            source, dest = entry
        else:
            source = dest = entry
        copy_file(source, work / "radial_heat" / dest)
    if override is not None:
        override(work)
    logs = root / label / "logs" / "verifier"
    logs.mkdir(parents=True)
    (root / label).chmod(0o755)
    logs.parent.chmod(0o777)
    logs.chmod(0o777)
    command = ["docker", "run", "--rm", "--user", "10001:10001", "--network", "host",
               "-v", f"{work}:/workspace:ro", "-v", f"{TASK / 'tests'}:/tests:ro",
               "-v", f"{logs.parent}:/logs", IMAGE, "bash", "/tests/test.sh"]
    outcome = run_command(command)
    reward_path = logs / "reward.txt"
    reward = float(reward_path.read_text(encoding="utf-8").strip()) if reward_path.exists() else None
    evidence = TASK / "solution" / "evidence" / f"{label}.log"
    groups = {}
    for group in GROUPS:
        group_log = logs / f"{group}.log"
        groups[group] = group_log.read_text(encoding="utf-8") if group_log.exists() else "missing"
    evidence.write_text(
        "Command: " + " ".join(command) + "\n"
        + f"Exit: {outcome.returncode}\nReward: {reward}\n"
        + "stdout:\n" + outcome.stdout + "\nstderr:\n" + outcome.stderr
        + "\n".join(f"\n[{group}]\n{log}" for group, log in groups.items()),
        encoding="utf-8")
    if reward is None:
        raise RuntimeError(f"{label}: no reward; inspect {evidence}")
    print(f"{label}: {reward}")
    return {"reward": reward, "evidence": str(evidence.relative_to(TASK))}


def empty_output(work):
    module = work / "radial_heat" / "solver.py"
    module.write_text("def simulate(data):\n    return {'records': []}\n", encoding="utf-8")


def fixed_example(work):
    module = work / "radial_heat" / "solver.py"
    module.write_text("def simulate(data):\n    return {'records': [{'time_s': 0, 'temperatures_c': [75]}]}\n",
                      encoding="utf-8")


def drop_solver(work):
    (work / "radial_heat" / "solver.py").unlink()


def main():
    build = run_command(["docker", "build", "-q", "-t", IMAGE, str(TASK / "environment")])
    if build.returncode:
        raise RuntimeError(build.stderr)
    (TASK / "solution" / "evidence").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="radial-quality-") as temp:
        root = Path(temp)
        root.chmod(0o755)
        baseline = specimen(root, "baseline", [])
        oracle = specimen(root, "oracle", ["geometry.py", "boundary.py", "solver.py"])
        partials = [
            {"challenge_id": "C1", **specimen(root, "partial-c1", ["geometry.py"])},
            {"challenge_id": "C2", **specimen(root, "partial-c2", [("boundary_c2.py", "boundary.py")])},
            {"challenge_id": "C3", **specimen(root, "partial-c3", [("solver_c3.py", "solver.py")])},
            {"challenge_id": "C4", **specimen(root, "partial-c4", [("solver_c4.py", "solver.py")])},
            {"challenge_id": "C5", **specimen(root, "partial-c5", [("boundary_c5.py", "boundary.py")])},
        ]
        bypasses = [
            {"id": "B1", "description": "仅返回空记录数组", **specimen(root, "bypass-empty", [], empty_output)},
            {"id": "B2", "description": "固定返回一条公开样例记录", **specimen(root, "bypass-fixed", [], fixed_example)},
            {"id": "B3", "description": "删除核心求解模块", **specimen(root, "bypass-delete", [], drop_solver)},
        ]
    report = {"baseline": baseline, "oracle": oracle, "partials": partials, "bypasses": bypasses}
    (TASK / "solution" / "quality-gate-results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if baseline["reward"] != 0 or oracle["reward"] != 1:
        raise RuntimeError("baseline/oracle gate failed")
    if any(not 0 < p["reward"] < 1 for p in partials):
        raise RuntimeError("partial gate failed")
    if any(p["reward"] == 1 for p in bypasses):
        raise RuntimeError("bypass gate failed")


if __name__ == "__main__":
    main()
