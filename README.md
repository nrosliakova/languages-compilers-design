# Languages and Compilers Design — Practice 5

A compiler with if/else, boolean negation, nested scopes, and LLVM control flow.

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

The current suite contains 15 valid and 20 invalid tests.
Practice 5 adds 7 valid and 10 invalid tests.
AST dumps for the new valid programs are saved beside their sources.

Implementation lives in src/.
Root-level compiler.py and lexer.py preserve compatibility with earlier commands
and manual test imports.

The optional while extension is not implemented.
