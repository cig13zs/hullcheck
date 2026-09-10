"""Fixture tests: every check must fire on the asset built to break it.

Runs Blender headless once per fixture, reads the JSON report, and asserts the
expected check IDs. Also asserts exit codes: broken assets must exit non-zero,
good assets must exit zero.

    python tests/run_tests.py
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BLENDER = os.environ.get(
    "HULLCHECK_BLENDER",
    r"C:\Program Files\Blender Foundation\Blender 4.4\blender.exe",
)
CHECKER = os.path.join(ROOT, "hullcheck.py")
FIXTURES = os.path.join(HERE, "fixtures")

# fixture -> (must-contain check ids, must-NOT-contain, expected exit code 0/1)
CASES = {
    "good.blend": ([], ["uv.missing", "normals.inverted", "geometry.nonmanifold"], 0),
    "bad_uvs.blend": (["uv.missing"], [], 1),
    "bad_normals.blend": (["normals.inverted"], [], 1),
    "bad_ngons.blend": (["geometry.ngons"], [], 0),
    "bad_loose.blend": (["geometry.loose"], [], 0),
    "bad_scale.blend": (["transform.unapplied", "size.too_large"], [], 1),
    "bad_tris.blend": (["budget.exceeded"], [], 1),
    "bad_doubles.blend": (["geometry.doubles"], [], 0),
    "empty.blend": (["scene.no_meshes"], [], 0),
}


def run_blender(args, timeout=240):
    proc = subprocess.run(
        [BLENDER, "--background", "--factory-startup", "--python", args[0], "--"] + args[1:],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc


def build_fixtures():
    os.makedirs(FIXTURES, exist_ok=True)
    maker = os.path.join(HERE, "make_fixtures.py")
    proc = run_blender([maker, FIXTURES])
    missing = [n for n in CASES if not os.path.exists(os.path.join(FIXTURES, n))]
    if missing:
        print("fixture build failed; missing:", missing)
        print(proc.stdout[-2000:])
        print(proc.stderr[-2000:])
        sys.exit(2)


def check_case(name, must, must_not, want_code, tmpdir):
    report_path = os.path.join(tmpdir, name + ".json")
    fixture = os.path.join(FIXTURES, name)
    proc = run_blender([CHECKER, fixture, "--json", report_path])
    failures = []

    if proc.returncode != want_code:
        failures.append("exit code %d, wanted %d" % (proc.returncode, want_code))
        failures.append("stdout tail: " + proc.stdout[-400:])

    if not os.path.exists(report_path):
        failures.append("no JSON report written")
        return failures

    with open(report_path, encoding="utf-8") as fh:
        data = json.load(fh)
    ids = {f["id"] for f in data["findings"]}
    for check_id in must:
        if check_id not in ids:
            failures.append("missing expected finding %s (got %s)" % (check_id, sorted(ids)))
    for check_id in must_not:
        if check_id in ids:
            failures.append("unexpected finding %s" % check_id)
    return failures


def check_fix(tmpdir):
    """--fix on the broken fixtures must clear the fixable findings."""
    failures = []
    for name, fixed_ids in [
        ("bad_loose.blend", {"geometry.loose"}),
        ("bad_scale.blend", {"transform.unapplied"}),
        ("bad_normals.blend", {"normals.inverted"}),
    ]:
        fixture = os.path.join(FIXTURES, name)
        out = os.path.join(tmpdir, name + ".fixed.json")
        pre = os.path.join(tmpdir, name + ".pre.json")
        run_blender([CHECKER, fixture, "--json", pre])
        run_blender([CHECKER, fixture, "--fix", "--json", out])
        if not os.path.exists(out):
            failures.append("%s: no report after --fix" % name)
            continue
        with open(out, encoding="utf-8") as fh:
            after = {f["id"] for f in json.load(fh)["findings"]}
        still = fixed_ids & after
        if still:
            failures.append("%s: --fix did not clear %s" % (name, sorted(still)))
    return failures


def check_export(tmpdir):
    """--export must write a real GLB."""
    failures = []
    glb = os.path.join(tmpdir, "good.glb")
    proc = run_blender([CHECKER, os.path.join(FIXTURES, "good.blend"), "--export", glb])
    if not os.path.exists(glb) or os.path.getsize(glb) < 100:
        failures.append("GLB export missing or too small")
        failures.append(proc.stdout[-400:])
    return failures


def main():
    build_fixtures()
    total, failed = 0, []
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, (must, must_not, want) in CASES.items():
            total += 1
            errs = check_case(name, must, must_not, want, tmpdir)
            status = "ok" if not errs else "FAIL"
            print("%-20s %s" % (name, status))
            for e in errs:
                print("    " + e)
            if errs:
                failed.append(name)
        for label, errs in [("--fix", check_fix(tmpdir)), ("--export", check_export(tmpdir))]:
            total += 1
            print("%-20s %s" % (label, "ok" if not errs else "FAIL"))
            for e in errs:
                print("    " + e)
            if errs:
                failed.append(label)

    print("")
    if failed:
        print("FAILED %d/%d: %s" % (len(failed), total, ", ".join(failed)))
        sys.exit(1)
    print("all %d fixture tests passed" % total)


if __name__ == "__main__":
    main()
