"""S-expressions as KiCad writes them: (name value (child ...) "quoted text")."""

import re

TOKEN = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))', re.DOTALL)
ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


class SexprError(ValueError):
    pass


class Quoted(str):
    """A value that was written in quotes (kept apart from bare words)."""


def _unescape(text: str) -> str:
    if "\\" not in text:
        return text
    return re.sub(r"\\(.)", lambda m: ESCAPES.get(m.group(1), m.group(1)), text)


def parse(text: str) -> list:
    """The first expression of the text as nested lists of strings."""
    stack: list[list] = []
    result: list | None = None
    pos = 0
    end = len(text)
    while pos < end:
        match = TOKEN.match(text, pos)
        if not match:
            if text[pos:].strip():
                raise SexprError(f"Непонятный текст в позиции {pos}")
            break
        pos = match.end()
        opening, closing, quoted, word = match.groups()
        if opening:
            node: list = []
            if stack:
                stack[-1].append(node)
            stack.append(node)
        elif closing:
            if not stack:
                raise SexprError("Лишняя закрывающая скобка")
            node = stack.pop()
            if not stack:
                result = node
                break
        elif quoted is not None:
            if not stack:
                raise SexprError("Текст вне скобок")
            stack[-1].append(Quoted(_unescape(quoted)))
        elif word is not None:
            if not stack:
                raise SexprError("Текст вне скобок")
            stack[-1].append(word)
    if result is None:
        raise SexprError("Файл обрывается: не хватает закрывающих скобок")
    return result


def name(node: object) -> str:
    return node[0] if isinstance(node, list) and node and isinstance(node[0], str) else ""


def children(node: list, key: str) -> list[list]:
    return [child for child in node[1:] if isinstance(child, list) and name(child) == key]


def child(node: list, key: str) -> list | None:
    for item in node[1:]:
        if isinstance(item, list) and name(item) == key:
            return item
    return None


def numbers(node: list | None, count: int, default: float = 0.0) -> list[float]:
    """The first count numbers after the node's name."""
    values: list[float] = []
    for item in (node or [])[1:]:
        if isinstance(item, str) and not isinstance(item, Quoted):
            try:
                values.append(float(item))
            except ValueError:
                continue
        if len(values) == count:
            break
    return values + [default] * (count - len(values))


def words(node: list | None) -> list[str]:
    return [item for item in (node or [])[1:] if isinstance(item, str)]
