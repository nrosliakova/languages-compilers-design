#!/usr/bin/env bash

set -u

passed=0
failed=0
ir_file="/tmp/practice2_test_$$.ll"
actual_file="/tmp/practice2_actual_$$.txt"

cleanup() {
    rm -f "$ir_file" "$actual_file"
}
trap cleanup EXIT

echo "Running valid tests..."

for source in tests/valid_*.src; do
    name="${source%.src}"
    expected="${name}.out"
    rm -f "$ir_file" "$actual_file"

    if python3 compiler.py "$source" "$ir_file" 2>"$actual_file"; then
        if lli "$ir_file" >"$actual_file" && diff -u "$expected" "$actual_file"; then
            echo "PASS: $source"
            passed=$((passed + 1))
        else
            echo "FAIL: $source"
            failed=$((failed + 1))
        fi
    else
        echo "FAIL: $source did not compile"
        cat "$actual_file"
        failed=$((failed + 1))
    fi
done

echo
echo "Running invalid tests..."

for source in tests/invalid_*.src; do
    name="${source%.src}"
    expected="${name}.err"
    rm -f "$ir_file" "$actual_file"

    if python3 compiler.py "$source" "$ir_file" 2>"$actual_file"; then
        echo "FAIL: $source compiled successfully"
        failed=$((failed + 1))
        continue
    fi

    if test -e "$ir_file"; then
        echo "FAIL: $source left an output IR file"
        failed=$((failed + 1))
        continue
    fi

    if diff -u "$expected" "$actual_file"; then
        echo "PASS: $source"
        passed=$((passed + 1))
    else
        echo "FAIL: $source"
        failed=$((failed + 1))
    fi
done

echo
echo "Passed: $passed"
echo "Failed: $failed"

if test "$failed" -ne 0; then
    exit 1
fi
