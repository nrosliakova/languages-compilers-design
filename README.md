# Languages and Compilers Design — Practice 4

This version includes the parser and AST foundation from Practice 3 and the typed semantic pass required for Practice 4.

## Pipeline

`source -> lexer -> parser -> AST -> semantic checker -> LLVM code generator`

## Requirements

- Python 3
- llvmlite
- LLVM `lli`

## Commands

```bash
python3 compiler.py --ast input.txt
python3 compiler.py input.txt output.ll
lli output.ll
./run_tests.sh
```

## Supported language

- `i32`, `i64`, and `bool`
- `const` by default and optional `mut`
- `+`, `-`, `*`, `==`, and `!=`
- implicit widening from `i32` to `i64`
- integer and boolean exits
