import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def normalized(data):
    return data.replace(b"\r\n", b"\n")


def check_test(source, valid, workdir):
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

        executed = subprocess.run(
            ["lli", str(output)],
            capture_output=True,
        )

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


def main():
    if shutil.which("lli") is None:
        print("ERROR: lli was not found on PATH.")
        return 1

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
                success, detail = check_test(source, valid, workdir)

                result = "PASS" if success else "FAIL"
                kind = "valid" if valid else "invalid"
                print(f"{result:<8} {kind:<8} {source.relative_to(ROOT)}")

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
