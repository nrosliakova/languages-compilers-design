from dataclasses import dataclass


KEYWORDS = {
    "i32",
    "i64",
    "bool",
    "mut",
    "exit",
    "true",
    "false",
    "if",
    "else",
    "struct",
    "fn",
}


class LexError(Exception):
    def __init__(self, line, column, message):
        self.line = line
        self.column = column
        self.message = message
        super().__init__(message)


@dataclass
class Token:
    kind: str
    text: str
    line: int
    column: int


def is_letter(byte):
    return (
        ord("A") <= byte <= ord("Z")
        or ord("a") <= byte <= ord("z")
        or byte == ord("_")
    )


def is_digit(byte):
    return ord("0") <= byte <= ord("9")


def display_byte(byte):
    if byte is None:
        return "end of input"
    if 32 <= byte <= 126:
        return chr(byte)
    return f"\\x{byte:02x}"


def lex(data):
    lines = []
    tokens = []
    state = "START"
    i = 0
    line = 1
    column = 1
    start = 0
    start_line = 1
    start_column = 1

    while i <= len(data):
        byte = data[i] if i < len(data) else None

        if state == "START":
            if byte is None:
                break
            if byte in (ord(" "), ord("\t"), ord("\r")):
                pass
            elif byte == ord("\n"):
                tokens.append(Token("endline", "\\n", line, column))
                lines.append(tokens)
                tokens = []
                line += 1
                column = 0
            elif is_letter(byte):
                state = "IDENT"
                start = i
                start_line = line
                start_column = column
            elif is_digit(byte):
                state = "NUMBER"
                start = i
                start_line = line
                start_column = column
            elif byte == ord("{"):
                tokens.append(Token("block", "{", line, column))
            elif byte == ord("}"):
                tokens.append(Token("block", "}", line, column))
            elif byte in (ord("+"), ord("*")):
                tokens.append(Token("operator", chr(byte), line, column))
            elif byte == ord("-"):
                state = "DASH"
                start_line = line
                start_column = column
            elif byte == ord(","):
                tokens.append(Token("operator", ",", line, column))
            elif byte == ord("("):
                tokens.append(Token("operator", "(", line, column))
            elif byte == ord(")"):
                tokens.append(Token("operator", ")", line, column))
            elif byte == ord(":"):
                state = "COLON"
                start_line = line
                start_column = column
            elif byte == ord("="):
                state = "EQUAL"
                start_line = line
                start_column = column
            elif byte == ord("!"):
                state = "BANG"
                start_line = line
                start_column = column
            else:
                raise LexError(
                    line,
                    column,
                    f"unexpected byte '{display_byte(byte)}'",
                )

        elif state == "IDENT":
            if byte is not None and (is_letter(byte) or is_digit(byte)):
                pass
            else:
                text = data[start:i].decode("ascii")
                kind = "keyword" if text in KEYWORDS else "identifier"
                tokens.append(Token(kind, text, start_line, start_column))
                state = "START"
                continue

        elif state == "NUMBER":
            if byte is not None and is_digit(byte):
                pass
            elif byte is not None and is_letter(byte):
                raise LexError(
                    line,
                    column,
                    "a letter cannot appear inside a number",
                )
            else:
                text = data[start:i].decode("ascii")
                tokens.append(Token("number", text, start_line, start_column))
                state = "START"
                continue

        elif state == "COLON":
            if byte == ord("="):
                tokens.append(
                    Token("operator", ":=", start_line, start_column)
                )
                state = "START"
            else:
                raise LexError(
                    start_line,
                    start_column,
                    "':' must be followed by '='",
                )

        elif state == "EQUAL":
            if byte == ord("="):
                tokens.append(
                    Token("operator", "==", start_line, start_column)
                )
                state = "START"
            else:
                raise LexError(
                    start_line,
                    start_column,
                    "expected '==' (a single '=' is not an operator)",
                )

        elif state == "BANG":
            if byte == ord("="):
                tokens.append(
                    Token("operator", "!=", start_line, start_column)
                )
                state = "START"
            else:
                tokens.append(
                    Token("operator", "!", start_line, start_column)
                )
                state = "START"
                continue

        elif state == "DASH":
            if byte == ord(">"):
                tokens.append(
                    Token("operator", "->", start_line, start_column)
                )
                state = "START"
            else:
                tokens.append(
                    Token("operator", "-", start_line, start_column)
                )
                state = "START"
                continue

        i += 1
        column += 1

    if tokens:
        lines.append(tokens)

    return lines
