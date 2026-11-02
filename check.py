import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def normalized(data):
    return data.replace(b"\r\n", b"\n")


def compiler_flags():
    flags = []
    if os.environ.get("REMOVE_UNUSED") == "1":
        flags.append("--remove-unused")
    for argument in sys.argv[1:]:
        if argument == "--remove-unused":
            if argument not in flags:
                flags.append(argument)
        else:
            print(f"unknown option: {argument}", file=sys.stderr)
            print("usage: python3 check.py [--remove-unused]", file=sys.stderr)
            raise SystemExit(2)
    return flags


def run_program(output, source):
    return subprocess.run(
        ["lli", str(output)],
        input=source.with_suffix(".in").read_bytes()
        if source.with_suffix(".in").exists() else b"",
        capture_output=True,
        timeout=10,
    )


def check_test(source, valid, workdir, flags):
    expected_path = source.with_suffix(".expected")
    if not expected_path.exists():
        return False, "missing .expected file"

    expected = normalized(expected_path.read_bytes())
    output = workdir / "output.ll"
    output.unlink(missing_ok=True)

    compiled = subprocess.run(
        [
            sys.executable,
            str(ROOT / "src" / "compiler.py"),
            *flags,
            str(source),
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
    )

    if valid:
        if compiled.returncode != 0:
            return False, compiled.stderr.decode(errors="replace").strip()

        if not output.exists():
            return False, "compiler produced no IR file"

        executed = run_program(output, source)

        if executed.returncode != 0:
            return False, executed.stderr.decode(errors="replace").strip()

        actual = normalized(executed.stdout)
    else:
        if compiled.returncode == 0:
            return False, "invalid program compiled successfully"

        if output.exists():
            return False, "failed compilation left an IR file"

        actual = normalized(compiled.stderr)

    if actual != expected:
        return False, f"expected {expected!r}; got {actual!r}"

    return True, ""


def check_opt_test(source, workdir):
    """The pass must leave the stored tree, and the program its stored output."""
    expected_tree = source.with_suffix(".astc")
    expected_output = source.with_suffix(".expected")
    if not expected_tree.exists():
        return False, "missing .astc file"
    if not expected_output.exists():
        return False, "missing .expected file"

    checked = subprocess.run(
        [
            sys.executable,
            str(ROOT / "src" / "compiler.py"),
            "--remove-unused",
            "--ast-checked",
            str(source),
        ],
        cwd=ROOT,
        capture_output=True,
    )
    if checked.returncode != 0:
        return False, checked.stderr.decode(errors="replace").strip()
    if normalized(checked.stdout) != normalized(expected_tree.read_bytes()):
        return False, "tree after the pass differs from the .astc file"

    expected = normalized(expected_output.read_bytes())
    for mode in ([], ["--remove-unused"]):
        output = workdir / "output.ll"
        output.unlink(missing_ok=True)
        compiled = subprocess.run(
            [
                sys.executable,
                str(ROOT / "src" / "compiler.py"),
                *mode,
                str(source),
                str(output),
            ],
            cwd=ROOT,
            capture_output=True,
        )
        if compiled.returncode != 0:
            return False, compiled.stderr.decode(errors="replace").strip()

        executed = run_program(output, source)
        if executed.returncode != 0:
            return False, executed.stderr.decode(errors="replace").strip()

        actual = normalized(executed.stdout)
        if actual != expected:
            label = "with the pass" if mode else "without the pass"
            return False, f"{label}: expected {expected!r}; got {actual!r}"

    return True, ""


def main():
    if shutil.which("lli") is None:
        print("ERROR: lli was not found on PATH.")
        return 1

    flags = compiler_flags()

    passed = 0
    failed = 0

    print(f"{'RESULT':<8} {'KIND':<8} TEST")
    print("-" * 72)

    with tempfile.TemporaryDirectory(prefix="pr5_check_") as directory:
        workdir = Path(directory)

        for folder, valid in [("ok", True), ("err", False)]:
            sources = sorted((ROOT / "tests" / folder).glob("*.txt"))

            if not sources:
                print(f"FAIL     {folder:<8} no tests found")
                failed += 1

            for source in sources:
                try:
                    success, detail = check_test(source, valid, workdir, flags)
                except subprocess.TimeoutExpired:
                    success, detail = False, "execution timed out after 10 seconds"

                result = "PASS" if success else "FAIL"
                kind = "valid" if valid else "invalid"
                print(f"{result:<8} {kind:<8} {source.relative_to(ROOT)}")

                if success:
                    passed += 1
                else:
                    failed += 1
                    print(f"         {detail}")

        for source in sorted((ROOT / "tests" / "opt").glob("*.txt")):
            try:
                success, detail = check_opt_test(source, workdir)
            except subprocess.TimeoutExpired:
                success, detail = False, "execution timed out after 10 seconds"

            result = "PASS" if success else "FAIL"
            print(f"{result:<8} {'optimize':<8} {source.relative_to(ROOT)}")

            if success:
                passed += 1
            else:
                failed += 1
                print(f"         {detail}")

    print()
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
