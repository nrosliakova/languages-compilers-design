import os
import sys

from llvmlite import ir
import llvmlite.binding as llvm

from lexer import LexError, lex


I32 = ir.IntType(32)
I8 = ir.IntType(8)


class CompileError(Exception):
    def __init__(self, line, column, message):
        self.line = line
        self.column = column
        self.message = message
        super().__init__(message)


def fail(token, message):
    raise CompileError(token.line, token.column, message)


def end_position(tokens):
    if tokens:
        token = tokens[-1]
        return token.line, token.column + len(token.text)

    return 1, 1


def read_operand(token, builder, symbols):
    if token.kind == "number":
        return ir.Constant(I32, int(token.text))

    if token.kind == "identifier":
        if token.text not in symbols:
            fail(
                token,
                f"variable '{token.text}' is used before its declaration",
            )

        return builder.load(
            symbols[token.text]["pointer"],
            name=f"{token.text}.value",
        )

    fail(token, "expected a number or variable")


def compile_expression(tokens, builder, symbols):
    if not tokens:
        raise CompileError(1, 1, "expected an expression")

    if len(tokens) == 1:
        return read_operand(tokens[0], builder, symbols)

    if len(tokens) != 3:
        fail(tokens[0], "invalid expression")

    left_token, operator_token, right_token = tokens

    if (
        operator_token.kind != "operator"
        or operator_token.text not in {"+", "-", "*"}
    ):
        fail(operator_token, "expected '+', '-' or '*'")

    left = read_operand(left_token, builder, symbols)
    right = read_operand(right_token, builder, symbols)

    if operator_token.text == "+":
        return builder.add(left, right, name="add.result")

    if operator_token.text == "-":
        return builder.sub(left, right, name="sub.result")

    return builder.mul(left, right, name="mul.result")


def compile_program(token_lines):
    module = ir.Module(name="practice2")
    module.triple = llvm.get_default_triple()

    main = ir.Function(
        module,
        ir.FunctionType(I32, []),
        name="main",
    )
    builder = ir.IRBuilder(main.append_basic_block("entry"))

    printf = ir.Function(
        module,
        ir.FunctionType(
            I32,
            [ir.PointerType(I8)],
            var_arg=True,
        ),
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
    last_line = 1

    for token_line in token_lines:
        tokens = [
            token
            for token in token_line
            if token.kind != "endline"
        ]

        if not tokens:
            continue

        last_line = tokens[0].line

        if saw_exit:
            fail(tokens[0], "no statement is allowed after exit")

        first = tokens[0]

        # Declaration:
        # i32 x{5}
        # i32 mut y{10}
        if first.kind == "keyword" and first.text == "i32":
            index = 1
            mutable = False

            if (
                index < len(tokens)
                and tokens[index].kind == "keyword"
                and tokens[index].text == "mut"
            ):
                mutable = True
                index += 1

            if index >= len(tokens):
                line, column = end_position(tokens)
                raise CompileError(
                    line,
                    column,
                    "expected a variable name",
                )

            name_token = tokens[index]

            if name_token.kind != "identifier":
                fail(name_token, "expected a variable name")

            name = name_token.text
            index += 1

            if name in symbols:
                fail(name_token, f"variable '{name}' is declared twice")

            if (
                index >= len(tokens)
                or tokens[index].kind != "block"
                or tokens[index].text != "{"
            ):
                if index < len(tokens):
                    fail(
                        tokens[index],
                        f"variable '{name}' needs an initialiser in {{}}",
                    )

                line, column = end_position(tokens)
                raise CompileError(
                    line,
                    column,
                    f"variable '{name}' needs an initialiser in {{}}",
                )

            left_brace = tokens[index]
            index += 1

            if (
                len(tokens) <= index
                or tokens[-1].kind != "block"
                or tokens[-1].text != "}"
            ):
                fail(
                    left_brace,
                    "'{' is not closed before the end of the line",
                )

            expression_tokens = tokens[index:-1]

            if not expression_tokens:
                fail(tokens[-1], "initializer cannot be empty")

            value = compile_expression(
                expression_tokens,
                builder,
                symbols,
            )

            pointer = builder.alloca(I32, name=name)
            builder.store(value, pointer)

            symbols[name] = {
                "pointer": pointer,
                "mutable": mutable,
            }
            continue

        # Exit:
        # exit y
        # exit 42
        if first.kind == "keyword" and first.text == "exit":
            if len(tokens) != 2:
                fail(first, "exit requires exactly one value")

            value = read_operand(tokens[1], builder, symbols)
            fmt_pointer = builder.bitcast(
                fmt,
                ir.PointerType(I8),
            )

            builder.call(printf, [fmt_pointer, value])
            builder.ret(ir.Constant(I32, 0))
            saw_exit = True
            continue

        # Assignment:
        # y := 5
        # y := x + 3
        if first.kind == "identifier":
            name = first.text

            if name not in symbols:
                fail(
                    first,
                    f"variable '{name}' is used before its declaration",
                )

            if (
                len(tokens) < 3
                or tokens[1].kind != "operator"
                or tokens[1].text != ":="
            ):
                fail(first, "invalid assignment")

            if not symbols[name]["mutable"]:
                fail(
                    first,
                    f"cannot assign to '{name}': it is not mut",
                )

            value = compile_expression(
                tokens[2:],
                builder,
                symbols,
            )

            builder.store(value, symbols[name]["pointer"])
            continue

        fail(first, "invalid statement")

    if not saw_exit:
        raise CompileError(
            last_line + 1,
            1,
            "program has no exit statement",
        )

    return module


def main():
    if len(sys.argv) != 3:
        print(
            "usage: python3 compiler.py SOURCE OUTPUT.ll",
            file=sys.stderr,
        )
        return 1

    source_path = sys.argv[1]
    output_path = sys.argv[2]

    try:
        os.remove(output_path)
    except FileNotFoundError:
        pass

    try:
        with open(source_path, "rb") as source:
            token_lines = lex(source.read())

        module = compile_program(token_lines)

        with open(output_path, "w", encoding="utf-8") as output:
            output.write(str(module))

    except LexError as error:
        print(
            f"compilation error: line "
            f"{error.line}:{error.column}: {error.message}",
            file=sys.stderr,
        )
        return 1

    except CompileError as error:
        print(
            f"compilation error: line "
            f"{error.line}:{error.column}: {error.message}",
            file=sys.stderr,
        )
        return 1

    except OSError as error:
        print(f"compilation error: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
