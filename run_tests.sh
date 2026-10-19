#!/usr/bin/env bash
set -u
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
    if python3 src/compiler.py "$source" "$ir_file" 2>"$actual_file"; then
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
    if python3 src/compiler.py "$source" "$ir_file" 2>"$actual_file"; then
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
echo "Passed: $passed"
echo "Failed: $failed"
test "$failed" -eq 0
