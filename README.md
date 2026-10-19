# Languages and Compilers Design — Practice 7

A compiler with structs, member functions, mutation checking, input/output, and LLVM control flow.

## Pipeline

Source → lexer → parser → AST → semantic checker → LLVM code generator

## Requirements

- Python 3
- llvmlite installed for that Python interpreter
- LLVM lli and opt available on PATH

## Commands

Run from the repository root:

```bash
python3 src/compiler.py --ast tests/ok/if_nested.txt
python3 src/compiler.py tests/ok/if_else_assignment.txt output.ll
lli output.ll
python3 check.py
```

Inspect register promotion:

```bash
python3 src/compiler.py tests/ok/assignment_both_arms.txt output.ll
opt -passes=mem2reg -S output.ll -o promoted.ll
grep 'phi ' promoted.ll
lli promoted.ll
```

## Supported language

- i32, i64, and bool
- Immutable declarations by default; optional mut
- Arithmetic: +, -, *
- Comparisons: ==, !=
- Boolean negation: !
- Implicit widening from i32 to i64
- if with optional else and nested multiline blocks
- Integer and boolean exits, including exits inside branches

Braces and else must stand alone on their lines.
Blocks cannot be empty, and exit must be their final statement.
Parentheses and unary minus are not supported.

## Semantic checking

Each block has its own scope.
Declarations may shadow outer names, including with a different type.
Duplicate declarations within one scope are rejected.
Variable uses and assignments retain references to their resolved declarations.
Conditions and operands of ! must be bool.
Diagnostics include line and column.

## LLVM generation

IR is built through llvmlite.ir, not assembled from strings.
All variable allocations are placed at the beginning of entry.
Initializers and stores execute at their declaration locations.
Branches use LLVM block objects.
An arm that returns receives no additional branch.
LLVM mem2reg creates phi instructions from the generated loads and stores.

## Tests

python3 check.py runs tests/ok/*.txt and tests/err/*.txt.
Each test has a matching .expected file.
Comparisons normalize CRLF/LF line endings.
Failed compilation must not leave an output IR file.

The current suite contains 48 valid and 88 invalid tests (136 total).
AST dumps for the new valid programs are saved beside their sources.

Implementation lives in src/.
Root-level compiler.py and lexer.py preserve compatibility with earlier commands
and manual test imports.

The while extension is implemented, including print and read inside its body.


## Practice 7

The required member-function, I/O, and testing tasks are implemented.
The optional call-in-the-middle-of-a-chain task is also implemented.

- Structs contain fields first, then methods. Methods have their own per-struct namespace.
- Parameters and local variables hide object fields. Methods do not see top-level variables.
- An unqualified call inside a method prefers a method on the same object, then a global function.
- Mutation flags propagate through calls until a fixed point, including cycles.
- A mutating call requires a mutable receiver and every field along its receiver chain.
- LLVM methods receive the original object's address as a hidden first argument.
- read() returns i32 and takes no arguments. read and print are reserved names.
- print accepts i32, i64, bool, a literal, or a struct, and emits one trailing newline.
- Literal backslashes are not escapes. Percent signs are printed as text.
- Struct printing recursively follows the declared fields, including returned structs.
- Calls returning structs can be followed by fields and member calls.
- A call result is a temporary copy; mutating it does not change the original object.
- Call results cannot be assignment targets.
- Both runners use a matching NAME.in file when present and compare the whole stdout.

### Demonstration commands

```bash
python3 src/compiler.py --ast tests/ok/pr7_task1.txt
python3 src/compiler.py tests/ok/pr7_task1.txt output.ll
lli output.ll
# Program exit with result 83

grep -n -A 25 'define.*Point_shift' output.ll

python3 src/compiler.py tests/ok/pr7_print_all.txt output.ll
lli output.ll < tests/ok/pr7_print_all.in

python3 src/compiler.py tests/err/pr7_field_after_method.txt output.ll
python3 src/compiler.py tests/err/pr7_mutating_const.txt output.ll
# Both commands must fail with line:column diagnostics.

python3 src/compiler.py tests/ok/pr7_bonus_example.txt output.ll
lli output.ll
# Program exit with result 46

python3 check.py
bash run_tests.sh
# Both: Passed: 136, Failed: 0
```

On a new machine, install llvmlite for the Python interpreter being used,
and make sure LLVM's lli is on PATH. See PRACTICE7_CHANGES.md for the change guide.
