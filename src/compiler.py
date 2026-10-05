import os
import sys
from dataclasses import dataclass, field

from llvmlite import ir
import llvmlite.binding as llvm

if __package__:
    from .lexer import LexError, lex
else:
    from lexer import LexError, lex

I1 = ir.IntType(1)
I8 = ir.IntType(8)
I32 = ir.IntType(32)
I64 = ir.IntType(64)
MAX_I32 = 2**31 - 1
MAX_I64 = 2**63 - 1


class CompileError(Exception):
    def __init__(self, line, column, message):
        self.line = line
        self.column = column
        self.message = message
        super().__init__(message)


@dataclass
class Node:
    line: int
    column: int

    def accept(self, visitor):
        method_name = "visit_" + self.__class__.__name__.replace("Node", "").lower()
        return getattr(visitor, method_name)(self)


@dataclass
class ProgramNode(Node):
    statements: list
    exit_node: object


@dataclass
class BlockNode(Node):
    statements: list
    exit_node: object = None


@dataclass
class IfNode(Node):
    condition: object
    then_block: BlockNode
    else_block: object = None


@dataclass
class DeclNode(Node):
    name: str
    type_name: str
    mutable: bool
    init: object
    pointer: object = field(default=None, init=False, repr=False)


@dataclass
class AssignNode(Node):
    name: str
    value: object
    decl: object = field(default=None, init=False, repr=False)


@dataclass
class ExitNode(Node):
    value: object


@dataclass
class ExprNode(Node):
    type: str = field(default=None, init=False)


@dataclass
class BinOpNode(ExprNode):
    op: str
    left: object
    right: object


@dataclass
class VarNode(ExprNode):
    name: str
    decl: object = field(default=None, init=False, repr=False)


@dataclass
class ConstNode(ExprNode):
    value: int


@dataclass
class BoolNode(ExprNode):
    value: bool


@dataclass
class NotNode(ExprNode):
    operand: object


class Parser:
    def __init__(self, lines):
        self.lines = lines
        self.line_pos = -1
        self.tokens = []
        self.pos = 0

    def next_line(self):
        self.line_pos += 1

        while self.line_pos < len(self.lines):
            self.tokens = [
                token
                for token in self.lines[self.line_pos]
                if token.kind != "endline"
            ]
            self.pos = 0

            if self.tokens:
                return True

            self.line_pos += 1

        self.tokens = []
        self.pos = 0
        return False

    def peek_line(self):
        index = self.line_pos + 1

        while index < len(self.lines):
            tokens = [
                token
                for token in self.lines[index]
                if token.kind != "endline"
            ]
            if tokens:
                return tokens
            index += 1

        return None

    def expect_line_end(self):
        token = self.peek()
        if token is not None:
            raise CompileError(
                token.line,
                token.column,
                f"unexpected '{token.text}' after the statement",
            )

    def peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def eat(self):
        token = self.peek()
        if token is not None:
            self.pos += 1
        return token

    def at(self, text):
        token = self.peek()
        return token is not None and token.text == text

    def end_position(self):
        if self.tokens:
            token = self.tokens[-1]
            return token.line, token.column + len(token.text)
        return 1, 1

    def error_here(self, message):
        token = self.peek()
        if token is not None:
            raise CompileError(token.line, token.column, message)
        line, column = self.end_position()
        raise CompileError(line, column, message)

    def expect_text(self, text, message=None):
        token = self.peek()
        if token is None or token.text != text:
            self.error_here(message or f"expected '{text}'")
        return self.eat()

    def expect_kind(self, kind, message):
        token = self.peek()
        if token is None or token.kind != kind:
            self.error_here(message)
        return self.eat()

    def parse_program(self):
        statements = []
        exit_node = None
        last_line = 1

        while self.next_line():
            last_line = self.tokens[0].line

            if exit_node is not None:
                token = self.tokens[0]
                raise CompileError(
                    token.line,
                    token.column,
                    "no statement is allowed after exit",
                )

            if self.at("exit"):
                exit_node = self.parse_exit()
            else:
                statements.append(self.parse_statement())

            if self.peek() is not None:
                token = self.peek()
                raise CompileError(
                    token.line,
                    token.column,
                    f"unexpected '{token.text}' after the statement",
                )

        if exit_node is None:
            raise CompileError(
                last_line + 1,
                1,
                "program has no exit statement",
            )

        return ProgramNode(1, 1, statements, exit_node)

    def parse_statement(self):
        token = self.peek()
        if token is None:
            self.error_here("expected a statement")

        if token.text in {"i32", "i64", "bool"}:
            return self.parse_decl()

        if token.text == "if":
            return self.parse_if()

        if token.text == "else":
            raise CompileError(
                token.line,
                token.column,
                "'else' without an 'if'",
            )

        if token.kind == "identifier":
            return self.parse_assign()

        raise CompileError(
            token.line,
            token.column,
            f"cannot start a statement with '{token.text}'",
        )

    def parse_if(self):
        if_token = self.eat()
        condition = self.parse_expr()
        self.expect_line_end()

        if not self.next_line():
            raise CompileError(
                if_token.line,
                if_token.column,
                "expected '{' on its own line after 'if', found end of input",
            )

        self.expect_text(
            "{",
            "expected '{' on its own line after 'if'",
        )
        then_block = self.parse_block()
        else_block = None

        following = self.peek_line()
        if following is not None and following[0].text == "else":
            self.next_line()
            else_token = self.eat()
            self.expect_line_end()

            if not self.next_line():
                raise CompileError(
                    else_token.line,
                    else_token.column,
                    "expected '{' on its own line after 'else', found end of input",
                )

            self.expect_text(
                "{",
                "expected '{' on its own line after 'else'",
            )
            else_block = self.parse_block()

        return IfNode(
            line=if_token.line,
            column=if_token.column,
            condition=condition,
            then_block=then_block,
            else_block=else_block,
        )

    def parse_block(self):
        opening = self.tokens[self.pos - 1]
        self.expect_line_end()

        statements = []
        exit_node = None

        while self.next_line():
            if self.at("}"):
                self.eat()
                self.expect_line_end()

                if not statements and exit_node is None:
                    raise CompileError(
                        opening.line,
                        opening.column,
                        "empty block",
                    )

                return BlockNode(
                    line=opening.line,
                    column=opening.column,
                    statements=statements,
                    exit_node=exit_node,
                )

            if exit_node is not None:
                token = self.peek()
                raise CompileError(
                    token.line,
                    token.column,
                    "statement after 'exit' in the same block",
                )

            if self.at("exit"):
                exit_node = self.parse_exit()
            else:
                statements.append(self.parse_statement())

            self.expect_line_end()

        raise CompileError(
            opening.line,
            opening.column,
            "'{' is never closed",
        )

    def parse_decl(self):
        type_token = self.eat()
        mutable = False
        if self.at("mut"):
            self.eat()
            mutable = True

        name = self.expect_kind("identifier", "expected a variable name")
        if not self.at("{"):
            self.error_here(
                f"variable '{name.text}' needs an initialiser in {{}}"
            )
        self.eat()
        init = self.parse_expr()
        self.expect_text("}", "expected '}' after the initialiser")
        return DeclNode(
            name.line,
            name.column,
            name.text,
            type_token.text,
            mutable,
            init,
        )

    def parse_assign(self):
        name = self.eat()
        self.expect_text(
            ":=",
            f"expected ':=' after '{name.text}'",
        )
        value = self.parse_expr()
        return AssignNode(name.line, name.column, name.text, value)

    def parse_exit(self):
        exit_token = self.eat()
        value = self.parse_factor()
        return ExitNode(exit_token.line, exit_token.column, value)

    def parse_expr(self):
        node = self.parse_arith()
        token = self.peek()
        if token is not None and token.text in {"==", "!="}:
            self.eat()
            node = BinOpNode(
                token.line,
                token.column,
                token.text,
                node,
                self.parse_arith(),
            )
        return node

    def parse_arith(self):
        node = self.parse_term()
        while self.peek() is not None and self.peek().text in {"+", "-"}:
            token = self.eat()
            node = BinOpNode(
                token.line,
                token.column,
                token.text,
                node,
                self.parse_term(),
            )
        return node

    def parse_term(self):
        node = self.parse_factor()
        while self.peek() is not None and self.peek().text == "*":
            token = self.eat()
            node = BinOpNode(
                token.line,
                token.column,
                token.text,
                node,
                self.parse_factor(),
            )
        return node

    def parse_factor(self):
        token = self.peek()
        if token is None:
            self.error_here(
                "expected a number, boolean or variable, found end of line"
            )
        if token.text == "!":
            self.eat()
            return NotNode(
                token.line,
                token.column,
                self.parse_factor(),
            )
        if token.kind == "number":
            self.eat()
            return ConstNode(token.line, token.column, int(token.text))
        if token.kind == "identifier":
            self.eat()
            return VarNode(token.line, token.column, token.text)
        if token.text in {"true", "false"}:
            self.eat()
            return BoolNode(token.line, token.column, token.text == "true")
        raise CompileError(
            token.line,
            token.column,
            f"expected a number, boolean or variable, got '{token.text}'",
        )


class AstPrinter:
    def __init__(self):
        self.lines = []
        self.depth = 0

    def add(self, text):
        self.lines.append("  " * self.depth + text)

    def child(self, node):
        self.depth += 1
        node.accept(self)
        self.depth -= 1

    def visit_program(self, node):
        self.add("Program")
        for statement in node.statements:
            self.child(statement)
        self.child(node.exit_node)
        return "\n".join(self.lines)

    def visit_block(self, node):
        self.add("Block")
        for statement in node.statements:
            self.child(statement)
        if node.exit_node is not None:
            self.child(node.exit_node)

    def visit_if(self, node):
        self.add("If")
        self.child(node.condition)
        self.child(node.then_block)
        if node.else_block is not None:
            self.child(node.else_block)

    def visit_decl(self, node):
        mutability = "mut" if node.mutable else "const"
        self.add(f"Decl {node.name} {node.type_name} {mutability}")
        self.child(node.init)

    def visit_assign(self, node):
        self.add(f"Assign {node.name}")
        self.child(node.value)

    def visit_exit(self, node):
        self.add("Exit")
        self.child(node.value)

    def visit_binop(self, node):
        self.add(f"BinOp {node.op}")
        self.child(node.left)
        self.child(node.right)

    def visit_var(self, node):
        self.add(f"Var {node.name}")

    def visit_const(self, node):
        self.add(f"Const {node.value}")

    def visit_bool(self, node):
        self.add("Bool true" if node.value else "Bool false")

    def visit_not(self, node):
        self.add("Not")
        self.child(node.operand)


class SemanticChecker:
    def __init__(self):
        self.scopes = [{}]

    def lookup(self, node, name):
        for frame in reversed(self.scopes):
            if name in frame:
                return frame[name]

        raise CompileError(
            node.line,
            node.column,
            f"variable '{name}' is used before its declaration",
        )

    def check(self, program):
        program.accept(self)

    def visit_program(self, node):
        for statement in node.statements:
            statement.accept(self)
        node.exit_node.accept(self)

    def visit_block(self, node):
        self.scopes.append({})

        try:
            for statement in node.statements:
                statement.accept(self)

            if node.exit_node is not None:
                node.exit_node.accept(self)
        finally:
            self.scopes.pop()

    def visit_decl(self, node):
        current_scope = self.scopes[-1]

        if node.name in current_scope:
            raise CompileError(
                node.line,
                node.column,
                f"variable '{node.name}' is already declared in this block",
            )

        node.init.accept(self)
        self.check_assignable(
            node.init,
            node.type_name,
            node,
            f"initialise '{node.name}'",
        )

        current_scope[node.name] = node

    def visit_assign(self, node):
        decl = self.lookup(node, node.name)

        if not decl.mutable:
            raise CompileError(
                node.line,
                node.column,
                f"cannot assign to '{node.name}': it is not mut",
            )

        node.decl = decl
        node.value.accept(self)

        self.check_assignable(
            node.value,
            decl.type_name,
            node,
            f"assign to '{node.name}'",
        )

    def visit_if(self, node):
        condition_type = node.condition.accept(self)

        if condition_type != "bool":
            raise CompileError(
                node.line,
                node.column,
                f"the condition of 'if' must be bool, got {condition_type}",
            )

        node.then_block.accept(self)

        if node.else_block is not None:
            node.else_block.accept(self)

    def visit_exit(self, node):
        node.value.accept(self)

    def visit_var(self, node):
        decl = self.lookup(node, node.name)
        node.decl = decl
        node.type = decl.type_name
        return node.type

    def visit_const(self, node):
        if node.value <= MAX_I32:
            node.type = "i32"
        elif node.value <= MAX_I64:
            node.type = "i64"
        else:
            raise CompileError(
                node.line,
                node.column,
                f"constant {node.value} does not fit in i64",
            )
        return node.type

    def visit_bool(self, node):
        node.type = "bool"
        return node.type

    def visit_binop(self, node):
        left_type = node.left.accept(self)
        right_type = node.right.accept(self)

        if node.op in {"+", "-", "*"}:
            if left_type == "bool" or right_type == "bool":
                raise CompileError(
                    node.line,
                    node.column,
                    f"cannot apply '{node.op}' to bool",
                )
            node.type = (
                "i64"
                if left_type == "i64" or right_type == "i64"
                else "i32"
            )
            return node.type

        left_is_int = left_type in {"i32", "i64"}
        right_is_int = right_type in {"i32", "i64"}
        if left_is_int and right_is_int:
            node.type = "bool"
            return node.type
        if left_type == "bool" and right_type == "bool":
            node.type = "bool"
            return node.type
        raise CompileError(
            node.line,
            node.column,
            f"cannot compare {left_type} with {right_type}",
        )

    def visit_not(self, node):
        operand_type = node.operand.accept(self)

        if operand_type != "bool":
            raise CompileError(
                node.line,
                node.column,
                f"cannot apply '!' to {operand_type}",
            )

        node.type = "bool"
        return node.type

    def check_assignable(self, expr, want, at, action):
        have = expr.type
        if have == want or (have == "i32" and want == "i64"):
            return
        if isinstance(expr, ConstNode) and want == "i32" and have == "i64":
            raise CompileError(
                expr.line,
                expr.column,
                f"constant {expr.value} does not fit in i32",
            )
        raise CompileError(
            at.line,
            at.column,
            f"cannot {action} of type {want} "
            f"with a value of type {have}",
        )


class CodeGenerator:
    def __init__(self):
        self.module = ir.Module(name="practice4")
        self.module.triple = llvm.get_default_triple()
        self.main = ir.Function(
            self.module,
            ir.FunctionType(I32, []),
            name="main",
        )
        self.builder = ir.IRBuilder(self.main.append_basic_block("entry"))
        self.printf = ir.Function(
            self.module,
            ir.FunctionType(I32, [I8.as_pointer()], var_arg=True),
            name="printf",
        )
        self.int_format = self.global_string(
            "int_format",
            b"Program exit with result %lld\n\0",
        )
        self.bool_format = self.global_string(
            "bool_format",
            b"Program exit with result %s\n\0",
        )
        self.true_text = self.global_string("true_text", b"true\0")
        self.false_text = self.global_string("false_text", b"false\0")

    def global_string(self, name, data):
        array_type = ir.ArrayType(I8, len(data))
        value = ir.GlobalVariable(self.module, array_type, name=name)
        value.linkage = "private"
        value.global_constant = True
        value.initializer = ir.Constant(array_type, bytearray(data))
        return value

    def pointer(self, global_value):
        return self.builder.bitcast(global_value, I8.as_pointer())

    def llvm_type(self, type_name):
        return {"i32": I32, "i64": I64, "bool": I1}[type_name]

    def coerce(self, value, have, want):
        if have == "i32" and want == "i64":
            return self.builder.sext(value, I64, name="wide")
        return value

    def generate(self, program):
        program.accept(self)
        return self.module

    def visit_program(self, node):
        for statement in node.statements:
            statement.accept(self)
        node.exit_node.accept(self)

    def visit_not(self, node):
        value = node.operand.accept(self)
        return self.builder.not_(value, name="not.result")

    def create_entry_alloca(self, type_name, name):
        current_block = self.builder.block
        entry_block = self.main.entry_basic_block

        allocation_builder = ir.IRBuilder(entry_block)
        allocation_builder.position_at_start(entry_block)

        pointer = allocation_builder.alloca(
            self.llvm_type(type_name),
            name=name,
        )

        self.builder.position_at_end(current_block)
        return pointer

    def visit_decl(self, node):
        value = node.init.accept(self)
        value = self.coerce(value, node.init.type, node.type_name)

        node.pointer = self.create_entry_alloca(
            node.type_name,
            node.name,
        )

        self.builder.store(value, node.pointer)

    def visit_block(self, node):
        for statement in node.statements:
            statement.accept(self)

        if node.exit_node is not None:
            node.exit_node.accept(self)

    def visit_if(self, node):
        condition = node.condition.accept(self)

        then_block = self.main.append_basic_block("then")
        else_block = (
            self.main.append_basic_block("else")
            if node.else_block is not None
            else None
        )
        merge_block = self.main.append_basic_block("merge")

        self.builder.cbranch(
            condition,
            then_block,
            else_block if else_block is not None else merge_block,
        )

        self.builder.position_at_end(then_block)
        node.then_block.accept(self)

        if not self.builder.block.is_terminated:
            self.builder.branch(merge_block)

        if else_block is not None:
            self.builder.position_at_end(else_block)
            node.else_block.accept(self)

            if not self.builder.block.is_terminated:
                self.builder.branch(merge_block)

        self.builder.position_at_end(merge_block)

    def visit_assign(self, node):
        value = node.value.accept(self)
        value = self.coerce(
            value,
            node.value.type,
            node.decl.type_name,
        )
        self.builder.store(value, node.decl.pointer)

    def visit_exit(self, node):
        value = node.value.accept(self)
        if node.value.type == "bool":
            text = self.builder.select(
                value,
                self.pointer(self.true_text),
                self.pointer(self.false_text),
                name="bool.text",
            )
            self.builder.call(
                self.printf,
                [self.pointer(self.bool_format), text],
            )
        else:
            value = self.coerce(value, node.value.type, "i64")
            self.builder.call(
                self.printf,
                [self.pointer(self.int_format), value],
            )
        self.builder.ret(ir.Constant(I32, 0))

    def visit_var(self, node):
        return self.builder.load(
            node.decl.pointer,
            name=f"{node.name}.value",
        )

    def visit_const(self, node):
        return ir.Constant(self.llvm_type(node.type), node.value)

    def visit_bool(self, node):
        return ir.Constant(I1, int(node.value))

    def visit_binop(self, node):
        left = node.left.accept(self)
        right = node.right.accept(self)

        if node.op in {"+", "-", "*"}:
            left = self.coerce(left, node.left.type, node.type)
            right = self.coerce(right, node.right.type, node.type)
            if node.op == "+":
                return self.builder.add(left, right, name="add.result")
            if node.op == "-":
                return self.builder.sub(left, right, name="sub.result")
            return self.builder.mul(left, right, name="mul.result")

        if node.left.type in {"i32", "i64"}:
            compare_type = (
                "i64"
                if node.left.type == "i64" or node.right.type == "i64"
                else "i32"
            )
            left = self.coerce(left, node.left.type, compare_type)
            right = self.coerce(right, node.right.type, compare_type)
        predicate = "==" if node.op == "==" else "!="
        return self.builder.icmp_signed(
            predicate,
            left,
            right,
            name="compare.result",
        )


def load_program(source_path):
    with open(source_path, "rb") as source:
        lines = lex(source.read())
    return Parser(lines).parse_program()


def print_error(error):
    print(
        f"compilation error: line "
        f"{error.line}:{error.column}: {error.message}",
        file=sys.stderr,
    )


def main():
    ast_mode = len(sys.argv) == 3 and sys.argv[1] == "--ast"
    compile_mode = len(sys.argv) == 3 and sys.argv[1] != "--ast"

    if not ast_mode and not compile_mode:
        print(
            "usage:\n"
            "  python3 compiler.py SOURCE OUTPUT.ll\n"
            "  python3 compiler.py --ast SOURCE",
            file=sys.stderr,
        )
        return 1

    source_path = sys.argv[2] if ast_mode else sys.argv[1]
    output_path = None if ast_mode else sys.argv[2]

    if output_path is not None:
        try:
            os.remove(output_path)
        except FileNotFoundError:
            pass

    try:
        program = load_program(source_path)
        if ast_mode:
            print(program.accept(AstPrinter()))
            return 0

        SemanticChecker().check(program)
        module = CodeGenerator().generate(program)
        with open(output_path, "w", encoding="utf-8") as output:
            output.write(str(module))
    except (LexError, CompileError) as error:
        print_error(error)
        return 1
    except OSError as error:
        print(f"compilation error: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
