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
class FieldNode(Node):
    name: str
    type_name: str
    mutable: bool


@dataclass
class StructNode(Node):
    name: str
    fields: list

@dataclass
class ParamNode(Node):
    name: str
    type_name: str
    mutable: bool = False
    pointer: object = field(default=None, init=False, repr=False)


@dataclass
class FnNode(Node):
    name: str
    params: list
    result_type: str
    body: BlockNode
    llvm_fn: object = field(default=None, init=False, repr=False)

@dataclass
class DeclNode(Node):
    name: str
    type_name: str
    mutable: bool
    init: object
    extra_inits: list = field(default_factory=list)
    pointer: object = field(default=None, init=False, repr=False)


@dataclass
class AssignNode(Node):
    name: str
    value: object
    path: list = field(default_factory=list)
    target_type: object = field(default=None, init=False, repr=False)
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

@dataclass
class CallNode(ExprNode):
    name: str
    args: list
    fn: object = field(default=None, init=False, repr=False)


@dataclass
class FieldAccessNode(ExprNode):
    base: str
    path: list
    decl: object = field(default=None, init=False, repr=False)
    indices: list = field(default=None, init=False, repr=False)
    mut_flags: list = field(default=None, init=False, repr=False)


@dataclass
class InitListNode(ExprNode):
    values: list

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
        seen_fn = False
        seen_statement = False

        while self.next_line():
            last_line = self.tokens[0].line

            if exit_node is not None:
                token = self.tokens[0]
                raise CompileError(
                    token.line,
                    token.column,
                    "no statement is allowed after exit",
                )

            if self.at("struct") and (seen_fn or seen_statement):
                token = self.tokens[0]
                if seen_fn:
                    raise CompileError(
                        token.line,
                        token.column,
                        "a struct cannot be declared after a function",
                    )
                raise CompileError(
                    token.line,
                    token.column,
                    "a struct cannot be declared after a statement",
                )

            if self.at("fn") and seen_statement:
                token = self.tokens[0]
                raise CompileError(
                    token.line,
                    token.column,
                    "a function cannot be declared after a statement",
                )

            if self.at("exit"):
                exit_node = self.parse_exit()
            elif self.at("struct"):
                statements.append(self.parse_struct())
            elif self.at("fn"):
                seen_fn = True
                statements.append(self.parse_fn())
            else:
                seen_statement = True
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

        if token.text == "struct":
            raise CompileError(
                token.line,
                token.column,
                "a struct is declared only at the top level",
            )

        if token.text == "else":
            raise CompileError(
                token.line,
                token.column,
                "'else' without an 'if'",
            )
        if token.text == "fn":
            raise CompileError(
                token.line,
                token.column,
                "a function is declared only at the top level",
            )

        if token.kind == "identifier":
            following = (
                self.tokens[self.pos + 1]
                if self.pos + 1 < len(self.tokens)
                else None
            )
            if following is not None and (
                following.kind == "identifier"
                or following.text == "mut"
            ):
                return self.parse_decl()
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
        init = self.parse_init_value()
        extra_inits = []
        while self.at(","):
            self.eat()
            extra_inits.append(self.parse_init_value())
        self.expect_text("}", "expected '}' after the initialiser")
        return DeclNode(
            name.line,
            name.column,
            name.text,
            type_token.text,
            mutable,
            init,
            extra_inits,
        )

    def parse_struct(self):
        struct_token = self.eat()
        name = self.expect_kind("identifier", "expected a struct name")
        self.expect_line_end()

        if not self.next_line():
            raise CompileError(
                struct_token.line,
                struct_token.column,
                "expected '{' on its own line after 'struct', "
                "found end of input",
            )

        self.expect_text(
            "{",
            "expected '{' on its own line after 'struct'",
        )
        opening = self.tokens[self.pos - 1]
        fields = []

        while self.next_line():
            if self.at("}"):
                self.eat()
                self.expect_line_end()

                if not fields:
                    raise CompileError(
                        opening.line,
                        opening.column,
                        f"struct '{name.text}' has no fields",
                    )

                return StructNode(
                    line=struct_token.line,
                    column=struct_token.column,
                    name=name.text,
                    fields=fields,
                )

            type_token = self.eat()
            if (
                type_token.kind != "identifier"
                and type_token.text not in {"i32", "i64", "bool"}
            ):
                self.error_here("expected a field type")

            mutable = False
            if self.at("mut"):
                self.eat()
                mutable = True

            field_name = self.expect_kind(
                "identifier",
                "expected a field name",
            )
            self.expect_line_end()
            fields.append(
                FieldNode(
                    field_name.line,
                    field_name.column,
                    field_name.text,
                    type_token.text,
                    mutable,
                )
            )

        raise CompileError(
            opening.line,
            opening.column,
            "'{' is never closed",
        )

    def parse_fn(self):
        fn_token = self.eat()
        name = self.expect_kind("identifier", "expected a function name")
        self.expect_text(":=", "expected ':=' after the function name")
        self.expect_text("(", "expected '(' after ':='")

        params = []
        if not self.at(")"):
            while True:
                type_token = self.eat()
                if (
                    type_token.kind != "identifier"
                    and type_token.text not in {"i32", "i64", "bool"}
                ):
                    self.error_here("expected a parameter type")

                param_name = self.expect_kind(
                    "identifier",
                    "expected a parameter name",
                )
                params.append(
                    ParamNode(
                        param_name.line,
                        param_name.column,
                        param_name.text,
                        type_token.text,
                    )
                )

                if self.at(","):
                    self.eat()
                    continue
                break

        self.expect_text(")", "expected ')' after the parameters")
        self.expect_text("->", "expected '->' after the parameters")

        result_token = self.eat()
        if (
            result_token.kind != "identifier"
            and result_token.text not in {"i32", "i64", "bool"}
        ):
            self.error_here("expected a result type")
        self.expect_line_end()

        if not self.next_line():
            raise CompileError(
                fn_token.line,
                fn_token.column,
                "expected '{' on its own line after the function signature, "
                "found end of input",
            )

        self.expect_text(
            "{",
            "expected '{' on its own line after the function signature",
        )
        body = self.parse_block()

        if body.exit_node is None:
            raise CompileError(
                body.line,
                body.column,
                f"function '{name.text}' has no exit",
            )

        return FnNode(
            line=fn_token.line,
            column=fn_token.column,
            name=name.text,
            params=params,
            result_type=result_token.text,
            body=body,
        )

    def parse_assign(self):
        name = self.eat()
        path = []
        while self.at("."):
            self.eat()
            part = self.expect_kind(
                "identifier",
                "expected a field name after '.'",
            )
            path.append((part.text, part.line, part.column))
        self.expect_text(
            ":=",
            f"expected ':=' after '{name.text}'",
        )
        value = self.parse_expr()
        return AssignNode(name.line, name.column, name.text, value, path)

    def parse_field_access(self, name_token):
        path = []
        while self.at("."):
            self.eat()
            part = self.expect_kind(
                "identifier",
                "expected a field name after '.'",
            )
            path.append((part.text, part.line, part.column))
        return FieldAccessNode(
            name_token.line,
            name_token.column,
            name_token.text,
            path,
        )

    def parse_init_value(self):
        if self.at("{"):
            opening = self.eat()
            values = [self.parse_init_value()]
            while self.at(","):
                self.eat()
                values.append(self.parse_init_value())
            self.expect_text("}", "expected '}' after the nested initialiser")
            return InitListNode(opening.line, opening.column, values)
        return self.parse_expr()

    def parse_exit(self):
        exit_token = self.eat()
        value = self.parse_factor()
        return ExitNode(exit_token.line, exit_token.column, value)

    def parse_call(self, name_token):
        self.expect_text("(", "expected '(' after the function name")
        args = []
        if not self.at(")"):
            while True:
                args.append(self.parse_expr())
                if self.at(","):
                    self.eat()
                    continue
                break
        self.expect_text(")", "expected ')' after the arguments")
        return CallNode(
            name_token.line,
            name_token.column,
            name_token.text,
            args,
        )

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
            following = self.peek()
            if following is not None and following.text == "(":
                return self.parse_call(token)
            if following is not None and following.text == ".":
                return self.parse_field_access(token)
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
        for extra in node.extra_inits:
            self.child(extra)

    def visit_struct(self, node):
        self.add(f"Struct {node.name}")
        for struct_field in node.fields:
            self.child(struct_field)

    def visit_field(self, node):
        mutability = "mut" if node.mutable else "const"
        self.add(f"Field {node.name} {node.type_name} {mutability}")

    def visit_fn(self, node):
        self.add(f"Fn {node.name} -> {node.result_type}")
        for param in node.params:
            self.child(param)
        self.child(node.body)

    def visit_param(self, node):
        self.add(f"Param {node.name} {node.type_name}")

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

    def visit_call(self, node):
        self.add(f"Call {node.name}")
        for arg in node.args:
            self.child(arg)

    def visit_fieldaccess(self, node):
        chain = [node.base] + [part[0] for part in node.path]
        self.add(f"FieldAccess {'.'.join(chain)}")

    def visit_initlist(self, node):
        self.add("InitList")
        for value in node.values:
            self.child(value)


class SemanticChecker:
    def __init__(self):
        self.scopes = [{}]
        self.structs = {}
        self.fns = {}
        self.function = None

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
            if isinstance(statement, StructNode):
                statement.accept(self)
            elif isinstance(statement, FnNode):
                self.collect_fn(statement)

        for statement in node.statements:
            if isinstance(statement, StructNode):
                continue
            statement.accept(self)

        node.exit_node.accept(self)

    def collect_fn(self, node):
        if node.name in self.fns:
            raise CompileError(
                node.line,
                node.column,
                f"function '{node.name}' is already declared",
            )

        param_names = set()
        for param in node.params:
            if (
                param.type_name not in {"i32", "i64", "bool"}
                and param.type_name not in self.structs
            ):
                raise CompileError(
                    param.line,
                    param.column,
                    f"unknown type '{param.type_name}' "
                    f"of parameter '{param.name}'",
                )
            if param.name in param_names:
                raise CompileError(
                    param.line,
                    param.column,
                    f"parameter '{param.name}' is already declared "
                    f"in function '{node.name}'",
                )
            param_names.add(param.name)

        if (
            node.result_type not in {"i32", "i64", "bool"}
            and node.result_type not in self.structs
        ):
            raise CompileError(
                node.line,
                node.column,
                f"unknown type '{node.result_type}' "
                f"of result of function '{node.name}'",
            )

        self.fns[node.name] = node

    def visit_fn(self, node):
        params_frame = {}
        for param in node.params:
            params_frame[param.name] = param

        saved_scopes = self.scopes
        saved_function = self.function
        self.scopes = [params_frame]
        self.function = node

        try:
            node.body.accept(self)
        finally:
            self.scopes = saved_scopes
            self.function = saved_function

    def visit_call(self, node):
        fn = self.fns.get(node.name)

        if fn is None:
            raise CompileError(
                node.line,
                node.column,
                f"function '{node.name}' is not declared",
            )

        node.fn = fn

        if len(node.args) != len(fn.params):
            raise CompileError(
                node.line,
                node.column,
                f"function '{node.name}' needs {len(fn.params)} arguments, "
                f"got {len(node.args)}",
            )

        for param, arg in zip(fn.params, node.args):
            arg.accept(self)
            self.check_assignable(
                arg,
                param.type_name,
                arg,
                f"pass to '{param.name}' of '{fn.name}'",
            )

        node.type = fn.result_type
        return node.type

    def visit_fieldaccess(self, node):
        decl, indices, types, mut_flags = self.resolve_chain(
            node,
            node.base,
            node.path,
        )
        node.decl = decl
        node.indices = indices
        node.mut_flags = mut_flags
        node.type = types[-1]
        return node.type

    def visit_initlist(self, node):
        for value in node.values:
            value.accept(self)
        return None

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

        if (
            node.type_name not in {"i32", "i64", "bool"}
            and node.type_name not in self.structs
        ):
            raise CompileError(
                node.line,
                node.column,
                f"unknown type '{node.type_name}'",
            )

        node.init.accept(self)
        for extra in node.extra_inits:
            extra.accept(self)

        if node.type_name in self.structs:
            self.check_struct_init(node, self.structs[node.type_name])
        else:
            if node.extra_inits:
                raise CompileError(
                    node.extra_inits[0].line,
                    node.extra_inits[0].column,
                    f"'{node.type_name}' takes a single value in {{}}",
                )
            self.check_value_against(
                node.init,
                node.type_name,
                node,
                f"initialise '{node.name}'",
            )

        current_scope[node.name] = node

    def visit_struct(self, node):
        if node.name in self.structs:
            raise CompileError(
                node.line,
                node.column,
                f"struct '{node.name}' is already declared",
            )

        field_names = set()
        for struct_field in node.fields:
            if (
                struct_field.type_name not in {"i32", "i64", "bool"}
                and struct_field.type_name not in self.structs
            ):
                raise CompileError(
                    struct_field.line,
                    struct_field.column,
                    f"unknown type '{struct_field.type_name}' "
                    f"of field '{struct_field.name}'",
                )
            if struct_field.name in field_names:
                raise CompileError(
                    struct_field.line,
                    struct_field.column,
                    f"field '{struct_field.name}' is already declared "
                    f"in struct '{node.name}'",
                )
            field_names.add(struct_field.name)

        self.structs[node.name] = node

    def check_struct_init(self, node, struct_node):
        values = [node.init] + node.extra_inits
        fields = struct_node.fields

        if (
            len(values) == 1
            and isinstance(values[0], (VarNode, CallNode))
            and values[0].type == node.type_name
        ):
            return

        if len(values) != len(fields):
            raise CompileError(
                node.line,
                node.column,
                f"struct '{node.type_name}' needs {len(fields)} values "
                f"in {{}}, got {len(values)}",
            )

        for struct_field, value in zip(fields, values):
            self.check_value_against(
                value,
                struct_field.type_name,
                value,
                f"initialise '{struct_field.name}' of '{node.name}'",
            )

        return None

    def check_value_against(self, value, want, at, action):
        if isinstance(value, InitListNode):
            struct_node = self.structs.get(want)

            if struct_node is None:
                raise CompileError(
                    value.line,
                    value.column,
                    f"a {{}} initialiser needs a struct type, got {want}",
                )

            if len(value.values) != len(struct_node.fields):
                raise CompileError(
                    value.line,
                    value.column,
                    f"struct '{want}' needs {len(struct_node.fields)} values "
                    f"in {{}}, got {len(value.values)}",
                )

            for struct_field, sub_value in zip(struct_node.fields, value.values):
                self.check_value_against(
                    sub_value,
                    struct_field.type_name,
                    sub_value,
                    f"initialise '{struct_field.name}'",
                )

            value.type = want
            return

        self.check_assignable(value, want, at, action)

    def resolve_chain(self, at, base, path):
        decl = self.lookup(at, base)
        current = self.structs.get(decl.type_name)

        if current is None:
            raise CompileError(
                at.line,
                at.column,
                f"type '{decl.type_name}' has no fields",
            )

        indices = []
        types = [decl.type_name]
        mut_flags = [decl.mutable]

        for name, line, column in path:
            field_index = None
            struct_field = None
            for index, field_candidate in enumerate(current.fields):
                if field_candidate.name == name:
                    struct_field = field_candidate
                    field_index = index
                    break

            if struct_field is None:
                raise CompileError(
                    line,
                    column,
                    f"unknown field '{name}' in struct '{current.name}'",
                )

            indices.append(field_index)
            types.append(struct_field.type_name)
            mut_flags.append(struct_field.mutable)
            current = self.structs.get(struct_field.type_name)

        return decl, indices, types, mut_flags

    def struct_fully_mutable(self, struct_node):
        for struct_field in struct_node.fields:
            if not struct_field.mutable:
                return False
            field_struct = self.structs.get(struct_field.type_name)
            if field_struct is not None and not self.struct_fully_mutable(
                field_struct
            ):
                return False
        return True

    def visit_assign(self, node):
        chain = [node.name] + [part[0] for part in node.path]

        if node.path:
            decl, indices, types, mut_flags = self.resolve_chain(
                node,
                node.name,
                node.path,
            )
            node.decl = decl
            node.indices = indices
            node.target_type = types[-1]
            target_type = types[-1]

            for link, mutable in zip(chain, mut_flags):
                if not mutable:
                    raise CompileError(
                        node.line,
                        node.column,
                        f"cannot assign to '{'.'.join(chain)}': "
                        f"'{link}' is not mut",
                    )
        else:
            decl = self.lookup(node, node.name)
            node.decl = decl
            node.target_type = decl.type_name
            target_type = decl.type_name

            if not decl.mutable:
                raise CompileError(
                    node.line,
                    node.column,
                    f"cannot assign to '{node.name}': it is not mut",
                )

            if decl.type_name in self.structs and not self.struct_fully_mutable(
                self.structs[decl.type_name]
            ):
                raise CompileError(
                    node.line,
                    node.column,
                    f"cannot assign to '{node.name}': not all its fields are mut",
                )

        node.value.accept(self)

        self.check_assignable(
            node.value,
            target_type,
            node,
            f"assign to '{'.'.join(chain)}'",
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

        if self.function is not None:
            self.check_assignable(
                node.value,
                self.function.result_type,
                node,
                f"exit function '{self.function.name}'",
            )
        elif node.value.type not in {"i32", "i64", "bool"}:
            raise CompileError(
                node.line,
                node.column,
                "exit at the top level needs a built-in type",
            )

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
        self.struct_types = {}
        self.structs = {}
        self.module.triple = llvm.get_default_triple()
        self.main = ir.Function(
            self.module,
            ir.FunctionType(I32, []),
            name="main",
        )
        self.function = self.main
        self.fn_node = None
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
        if type_name in self.struct_types:
            return self.struct_types[type_name]
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
            if isinstance(statement, StructNode):
                statement.accept(self)
            elif isinstance(statement, FnNode):
                self.declare_fn(statement)

        for statement in node.statements:
            if isinstance(statement, StructNode):
                continue
            statement.accept(self)

        node.exit_node.accept(self)

    def declare_fn(self, node):
        fn_type = ir.FunctionType(
            self.llvm_type(node.result_type),
            [self.llvm_type(param.type_name) for param in node.params],
        )
        node.llvm_fn = ir.Function(
            self.module,
            fn_type,
            name="fn_" + node.name,
        )

    def visit_fn(self, node):
        fn = node.llvm_fn
        entry = fn.append_basic_block("entry")

        saved_builder = self.builder
        saved_function = self.function
        saved_fn_node = self.fn_node
        self.function = fn
        self.fn_node = node
        self.builder = ir.IRBuilder(entry)

        for param, argument in zip(node.params, fn.args):
            argument.name = param.name
            slot = self.create_entry_alloca(param.type_name, param.name)
            self.builder.store(argument, slot)
            param.pointer = slot

        node.body.accept(self)

        self.builder = saved_builder
        self.function = saved_function
        self.fn_node = saved_fn_node

    def visit_call(self, node):
        args = []
        for param, arg_node in zip(node.fn.params, node.args):
            value = arg_node.accept(self)
            value = self.coerce(value, arg_node.type, param.type_name)
            args.append(value)
        return self.builder.call(
            node.fn.llvm_fn,
            args,
            name=f"{node.name}.result",
        )

    def visit_fieldaccess(self, node):
        pointer = node.decl.pointer
        for index in node.indices:
            pointer = self.builder.gep(
                pointer,
                [ir.Constant(I32, 0), ir.Constant(I32, index)],
                name="field.ptr",
            )
        return self.builder.load(pointer, name="field.value")

    def build_struct_value(self, values, struct_node):
        value = ir.Constant(
            self.llvm_type(struct_node.name),
            ir.Undefined,
        )
        for index, (struct_field, value_node) in enumerate(
            zip(struct_node.fields, values)
        ):
            if isinstance(value_node, InitListNode):
                inner = self.build_struct_value(
                    value_node.values,
                    self.structs[struct_field.type_name],
                )
            else:
                inner = value_node.accept(self)
                inner = self.coerce(
                    inner,
                    value_node.type,
                    struct_field.type_name,
                )
            value = self.builder.insert_value(value, inner, index)
        return value

    def visit_struct(self, node):
        self.structs[node.name] = node
        struct_type = self.module.context.get_identified_type(node.name)
        self.struct_types[node.name] = struct_type
        struct_type.set_body(
            *[self.llvm_type(struct_field.type_name) for struct_field in node.fields]
        )

    def visit_not(self, node):
        value = node.operand.accept(self)
        return self.builder.not_(value, name="not.result")

    def create_entry_alloca(self, type_name, name):
        current_block = self.builder.block
        entry_block = self.function.entry_basic_block

        allocation_builder = ir.IRBuilder(entry_block)
        allocation_builder.position_at_start(entry_block)

        pointer = allocation_builder.alloca(
            self.llvm_type(type_name),
            name=name,
        )

        self.builder.position_at_end(current_block)
        return pointer

    def visit_decl(self, node):
        if node.type_name in self.structs:
            values = [node.init] + node.extra_inits
            struct_node = self.structs[node.type_name]

            node.pointer = self.create_entry_alloca(
                node.type_name,
                node.name,
            )

            if (
                len(values) == 1
                and isinstance(values[0], (VarNode, CallNode))
                and values[0].type == node.type_name
            ):
                value = values[0].accept(self)
                self.builder.store(value, node.pointer)
                return

            if len(values) == 1 and isinstance(values[0], InitListNode):
                value = self.build_struct_value(
                    values[0].values,
                    struct_node,
                )
                self.builder.store(value, node.pointer)
                return

            for index, (struct_field, value_node) in enumerate(
                zip(struct_node.fields, values)
            ):
                if isinstance(value_node, InitListNode):
                    field_value = self.build_struct_value(
                        value_node.values,
                        self.structs[struct_field.type_name],
                    )
                else:
                    field_value = value_node.accept(self)
                    field_value = self.coerce(
                        field_value,
                        value_node.type,
                        struct_field.type_name,
                    )
                slot = self.builder.gep(
                    node.pointer,
                    [ir.Constant(I32, 0), ir.Constant(I32, index)],
                    name=f"{node.name}.{struct_field.name}.ptr",
                )
                self.builder.store(field_value, slot)
            return

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

        then_block = self.function.append_basic_block("then")
        else_block = (
            self.function.append_basic_block("else")
            if node.else_block is not None
            else None
        )
        merge_block = self.function.append_basic_block("merge")

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
            node.target_type,
        )

        pointer = node.decl.pointer
        for index in node.indices if node.path else []:
            pointer = self.builder.gep(
                pointer,
                [ir.Constant(I32, 0), ir.Constant(I32, index)],
                name="field.ptr",
            )
        self.builder.store(value, pointer)

    def visit_exit(self, node):
        value = node.value.accept(self)

        if self.fn_node is not None:
            value = self.coerce(
                value,
                node.value.type,
                self.fn_node.result_type,
            )
            self.builder.ret(value)
            return

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
