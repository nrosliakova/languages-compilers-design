import os
import re
import sys

from llvmlite import ir
import llvmlite.binding as llvm


I32 = ir.IntType(32)
I8 = ir.IntType(8)
NAME = r"[A-Za-z_][A-Za-z0-9_]*"
OPERAND = rf"(?:-?\d+|{NAME})"


class CompileError(Exception):
    def __init__(self, line, message):
        self.line = line
        self.message = message


def compile_program(lines):
    module = ir.Module(name="practice1")
    module.triple = llvm.get_default_triple()

    main = ir.Function(
        module,
        ir.FunctionType(I32, []),
        name="main",
    )
    builder = ir.IRBuilder(main.append_basic_block("entry"))

    printf = ir.Function(
        module,
        ir.FunctionType(I32, [ir.PointerType(I8)], var_arg=True),
        name="printf",
    )

    text = b"Program exit with result %d\n\0"
    text_type = ir.ArrayType(I8, len(text))
    fmt = ir.GlobalVariable(module, text_type, name="fmt")
    fmt.linkage = "private"
    fmt.global_constant = True
    fmt.initializer = ir.Constant(text_type, bytearray(text))

    symbols = {}
    saw_exit = False

    def operand(token, line_number):
        if re.fullmatch(r"-?\d+", token):
            return ir.Constant(I32, int(token))

        if token not in symbols:
            raise CompileError(
                line_number,
                f"undeclared variable '{token}'",
            )

        return builder.load(symbols[token], name=f"{token}.value")

    for line_number, raw_line in enumerate(lines, 1):
        line = raw_line.strip()

        if not line:
            continue

        declaration = re.fullmatch(rf"int\s+({NAME})", line)
        if declaration:
            name = declaration.group(1)

            if name in symbols:
                raise CompileError(
                    line_number,
                    f"redeclared variable '{name}'",
                )

            symbols[name] = builder.alloca(I32, name=name)
            continue

        assignment = re.fullmatch(
            rf"({NAME})\s*:=\s*({OPERAND})"
            rf"(?:\s*([+*-])\s*({OPERAND}))?",
            line,
        )
        if assignment:
            target, left_text, operator, right_text = assignment.groups()

            if target not in symbols:
                raise CompileError(
                    line_number,
                    f"undeclared variable '{target}'",
                )

            value = operand(left_text, line_number)

            if operator is not None:
                right = operand(right_text, line_number)

                if operator == "+":
                    value = builder.add(value, right)
                elif operator == "-":
                    value = builder.sub(value, right)
                else:
                    value = builder.mul(value, right)

            builder.store(value, symbols[target])
            continue

        exit_statement = re.fullmatch(rf"exit\s+({OPERAND})", line)
        if exit_statement:
            value = operand(exit_statement.group(1), line_number)
            fmt_pointer = builder.bitcast(fmt, ir.PointerType(I8))
            builder.call(printf, [fmt_pointer, value])
            builder.ret(ir.Constant(I32, 0))
            saw_exit = True

            if line_number != len(lines):
                raise CompileError(
                    line_number,
                    "exit must be the last line",
                )
            continue

        raise CompileError(line_number, f"cannot parse '{line}'")

    if not saw_exit:
        raise CompileError(len(lines) + 1, "missing exit statement")

    return module


def main():
    if len(sys.argv) != 3:
        print(
            "usage: python3 compiler.py SOURCE OUTPUT.ll",
            file=sys.stderr,
        )
        return 1

    source_path, output_path = sys.argv[1], sys.argv[2]

    try:
        os.remove(output_path)
    except FileNotFoundError:
        pass

    try:
        with open(source_path, encoding="utf-8") as source:
            lines = source.read().splitlines()

        module = compile_program(lines)

        with open(output_path, "w", encoding="utf-8") as output:
            output.write(str(module))

    except CompileError as exc:
        print(
            f"compilation error: line {exc.line}: {exc.message}",
            file=sys.stderr,
        )
        return 1
    except OSError as exc:
        print(f"compilation error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
