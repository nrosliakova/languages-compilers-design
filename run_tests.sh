#!/usr/bin/env bash
set -u

usage() {
    echo "usage: bash run_tests.sh [--remove-unused]" >&2
    echo "       REMOVE_UNUSED=1 bash run_tests.sh" >&2
}

remove_unused=0
if test "${REMOVE_UNUSED:-0}" = "1"; then
    remove_unused=1
fi

for argument in "$@"; do
    case "$argument" in
        --remove-unused) remove_unused=1 ;;
        --help|-h) usage; exit 0 ;;
        *) echo "unknown option: $argument" >&2; usage; exit 2 ;;
    esac
done

flags=()
if test "$remove_unused" -eq 1; then
    flags=(--remove-unused)
    echo "Compiling every program with --remove-unused."
    echo
fi

passed=0
failed=0
ir_file="/tmp/practice4_test_$$.ll"
actual_file="/tmp/practice4_actual_$$.txt"
cleanup() { rm -f "$ir_file" "$actual_file"; }
trap cleanup EXIT

echo "Running valid tests..."
for source in tests/ok/*.txt; do
    expected="${source%.txt}.expected"
    rm -f "$ir_file" "$actual_file"
    if python3 src/compiler.py ${flags[@]+"${flags[@]}"} "$source" "$ir_file" 2>"$actual_file"; then
        input="${source%.txt}.in"
        if ! test -f "$input"; then input=/dev/null; fi
        if lli "$ir_file" <"$input" >"$actual_file" && diff -u "$expected" "$actual_file"; then
            echo "PASS: $source"; passed=$((passed + 1))
        else
            echo "FAIL: $source"; failed=$((failed + 1))
        fi
    else
        echo "FAIL: $source did not compile"; cat "$actual_file"; failed=$((failed + 1))
    fi
done

echo
echo "Running invalid tests..."
for source in tests/err/*.txt; do
    expected="${source%.txt}.expected"
    rm -f "$ir_file" "$actual_file"
    if python3 src/compiler.py ${flags[@]+"${flags[@]}"} "$source" "$ir_file" 2>"$actual_file"; then
        echo "FAIL: $source compiled successfully"; failed=$((failed + 1)); continue
    fi
    if test -e "$ir_file"; then
        echo "FAIL: $source left an output IR file"; failed=$((failed + 1)); continue
    fi
    if diff -u "$expected" "$actual_file"; then
        echo "PASS: $source"; passed=$((passed + 1))
    else
        echo "FAIL: $source"; failed=$((failed + 1))
    fi
done

echo
echo "Running optimization tests..."
for source in tests/opt/*.txt; do
    name="${source%.txt}"
    rm -f "$ir_file" "$actual_file"

    if ! python3 src/compiler.py --remove-unused --ast-checked "$source" >"$actual_file"; then
        echo "FAIL: $source did not check"; failed=$((failed + 1)); continue
    fi
    if ! diff -u "$name.astc" "$actual_file"; then
        echo "FAIL: $source tree after the pass"; failed=$((failed + 1)); continue
    fi

    result=pass
    for mode in plain remove; do
        mode_flags=()
        if test "$mode" = remove; then mode_flags=(--remove-unused); fi
        rm -f "$ir_file" "$actual_file"
        if ! python3 src/compiler.py ${mode_flags[@]+"${mode_flags[@]}"} "$source" "$ir_file" 2>"$actual_file"; then
            echo "FAIL: $source did not compile ($mode)"; cat "$actual_file"
            result=fail; break
        fi
        input="${source%.txt}.in"
        if ! test -f "$input"; then input=/dev/null; fi
        if ! lli "$ir_file" <"$input" >"$actual_file" || ! diff -u "$name.expected" "$actual_file"; then
            echo "FAIL: $source output ($mode)"
            result=fail; break
        fi
    done

    if test "$result" = pass; then
        echo "PASS: $source"; passed=$((passed + 1))
    else
        failed=$((failed + 1))
    fi
done

echo
echo "Passed: $passed"
echo "Failed: $failed"
test "$failed" -eq 0
