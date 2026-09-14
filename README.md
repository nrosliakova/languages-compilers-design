# Languages and Compilers Design

Practice 2 compiler implemented in Python with llvmlite.

## Requirements

- Python 3
- llvmlite 0.49
- LLVM tools, including `lli`, `llc`, and `clang`

## Compile and run

python3 compiler.py input.txt output.ll
lli output.ll

Alternatively:

llc -filetype=obj -relocation-model=pic output.ll -o output.o
clang -fPIE output.o -o program
./program

## Run tests

./run_tests.sh

## Language examples

i32 x{5}
i32 mut y{x + 10}
y := y * 2
exit y

The lexer is a hand-written state machine over ASCII bytes. It does not use regular expressions, `split()`, or a lexer generator.
