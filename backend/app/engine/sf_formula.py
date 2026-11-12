"""A small evaluator for Salesforce validation rule formulas, to test existing records against an org's active rules.

It covers the functions validation rules usually use (ISBLANK, ISPICKVAL, AND/OR, TEXT, LEN, REGEX, dates…). A formula that
uses something it can't work out from the record alone (the user saving it, custom settings, unsupported functions) raises
`Unsupported` when parsed, so that rule is reported as not checked instead of guessed.

Saving an existing record: ISNEW() and ISCHANGED() are false, PRIORVALUE(f) is the field's current value.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from typing import Any


class Unsupported(Exception):
    """The formula can't be checked against stored records (why is the message)."""


_TOKEN = re.compile(
    r"""\s*(?:
        (?P<num>\d+(?:\.\d+)?)
      | (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
      | (?P<op>&&|\|\||==|!=|<>|<=|>=|[=<>+\-*/&!(),^])
      | (?P<name>\$?[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)
    )""",
    re.X,
)
# Global variables that come from the user saving the record (or the org), not from the record itself.
_USER_GLOBALS = ("$user", "$profile", "$userrole", "$permission", "$setup", "$label", "$custommetadata", "$organization", "$api", "$system")

FUNCTIONS = {
    "AND", "OR", "NOT", "IF", "CASE", "ISBLANK", "ISNULL", "BLANKVALUE", "NULLVALUE", "ISPICKVAL", "TEXT", "LEN", "BEGINS", "CONTAINS",
    "INCLUDES", "REGEX", "ISNUMBER", "VALUE", "UPPER", "LOWER", "TRIM", "LEFT", "RIGHT", "MID", "SUBSTITUTE", "TODAY", "NOW",
    "DATEVALUE", "DATE", "YEAR", "MONTH", "DAY", "ABS", "MAX", "MIN", "ROUND", "FLOOR", "CEILING", "ISNEW", "ISCHANGED",
    "PRIORVALUE", "ISCLONE", "FIND",
}


def _tokens(text: str) -> list[tuple[str, str]]:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)  # comments
    out, pos = [], 0
    while pos < len(text):
        if text[pos:].strip() == "":
            break
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise Unsupported(f"can't read the formula near “{text[pos:pos + 20].strip()}”")
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
        pos = m.end()
    return out


class Formula:
    """A parsed formula: `fields` = the record fields it reads (SOQL paths, e.g. Account.Industry, RecordType.Name)."""

    def __init__(self, text: str):
        self.text = text
        self._t = _tokens(text)
        self._i = 0
        self.fields: list[str] = []
        self.tree = self._or()
        if self._i != len(self._t):
            raise Unsupported(f"can't read the formula near “{self._t[self._i][1]}”")

    # ---------------- parsing (|| < && < comparison < + - & < * / < ^ < unary)

    def _peek(self) -> str | None:
        return self._t[self._i][1] if self._i < len(self._t) else None

    def _take(self, want: str | None = None) -> tuple[str, str]:
        if self._i >= len(self._t):
            raise Unsupported("the formula ends too early")
        tok = self._t[self._i]
        if want is not None and tok[1] != want:
            raise Unsupported(f"expected “{want}” but found “{tok[1]}”")
        self._i += 1
        return tok

    def _binary(self, ops: tuple[str, ...], nxt):
        left = nxt()
        while self._peek() in ops:
            op = self._take()[1]
            left = ("op", op, left, nxt())
        return left

    def _or(self):
        return self._binary(("||",), self._and)

    def _and(self):
        return self._binary(("&&",), self._cmp)

    def _cmp(self):
        return self._binary(("=", "==", "!=", "<>", "<", ">", "<=", ">="), self._add)

    def _add(self):
        return self._binary(("+", "-", "&"), self._mul)

    def _mul(self):
        return self._binary(("*", "/"), self._pow)

    def _pow(self):
        return self._binary(("^",), self._unary)

    def _unary(self):
        if self._peek() in ("!", "-", "+"):
            op = self._take()[1]
            return ("un", op, self._unary())
        return self._primary()

    def _primary(self):
        kind, val = self._take()
        if kind == "num":
            return ("lit", float(val) if "." in val else int(val))
        if kind == "str":
            return ("lit", re.sub(r"\\(.)", r"\1", val[1:-1]))
        if val == "(":
            node = self._or()
            self._take(")")
            return node
        if kind != "name":
            raise Unsupported(f"unexpected “{val}”")
        up = val.upper()
        if self._peek() == "(":
            if up not in FUNCTIONS:
                raise Unsupported(f"uses {up}(), which this check can't work out")
            self._take("(")
            args = []
            if self._peek() != ")":
                args.append(self._or())
                while self._peek() == ",":
                    self._take(",")
                    args.append(self._or())
            self._take(")")
            return ("fn", up, args)
        if up in ("TRUE", "FALSE"):
            return ("lit", up == "TRUE")
        if up == "NULL":
            return ("lit", None)
        low = val.lower()
        if low.startswith("$recordtype."):
            path = "RecordType." + val.split(".", 1)[1]
        elif low.startswith("$"):
            if low.split(".")[0] in _USER_GLOBALS:
                raise Unsupported(f"depends on who saves the record ({val.split('.')[0]})")
            raise Unsupported(f"uses {val.split('.')[0]}")
        else:
            path = val
        if path not in self.fields:
            self.fields.append(path)
        return ("field", path)

    # ---------------- evaluation

    def __call__(self, record: dict) -> bool:
        """True when the formula's error condition is met, i.e. the record breaks the rule."""
        return _truth(_eval(self.tree, record))


def get_path(record: dict, path: str) -> Any:
    """A field from a SOQL record, by path (Account.Industry), ignoring case like Salesforce does."""
    cur: Any = record
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        low = part.lower()
        cur = next((v for k, v in cur.items() if k.lower() == low), None)
    return _as_value(cur)


_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _as_value(v: Any) -> Any:
    if isinstance(v, str):
        if _DATE.match(v):
            return date.fromisoformat(v)
        if _DATETIME.match(v):
            return datetime.fromisoformat(v[:19])
    if isinstance(v, dict):
        return None  # a related record (no field picked)
    return v


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _truth(v: Any) -> bool:
    return bool(v) if not isinstance(v, str) else v.lower() == "true"


def _text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%SZ")
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return v
    try:
        return float(str(v).strip())
    except ValueError:
        return None


def _compare(op: str, a: Any, b: Any) -> bool | None:
    if op in ("=", "==", "!=", "<>"):
        if _blank(a) and _blank(b):
            same = True
        elif _blank(a) or _blank(b):
            same = False
        elif isinstance(a, (int, float)) or isinstance(b, (int, float)):
            na, nb = _num(a), _num(b)
            same = na is not None and nb is not None and na == nb
        elif isinstance(a, datetime) != isinstance(b, datetime) and isinstance(a, date) and isinstance(b, date):
            same = (a.date() if isinstance(a, datetime) else a) == (b.date() if isinstance(b, datetime) else b)
        else:
            same = a == b
        return same if op in ("=", "==") else not same
    if _blank(a) or _blank(b):
        return None
    if isinstance(a, (int, float)) or isinstance(b, (int, float)):
        a, b = _num(a), _num(b)
        if a is None or b is None:
            return None
    elif isinstance(a, date) and isinstance(b, date) and isinstance(a, datetime) != isinstance(b, datetime):
        a = a.date() if isinstance(a, datetime) else a
        b = b.date() if isinstance(b, datetime) else b
    try:
        return {"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
    except TypeError:
        return None


def _arith(op: str, a: Any, b: Any) -> Any:
    if op == "&":
        return _text(a) + _text(b)
    if a is None or b is None:
        return None
    if isinstance(a, date) and op in ("+", "-") and isinstance(b, (int, float)) and not isinstance(b, bool):
        return a + timedelta(days=b) if op == "+" else a - timedelta(days=b)
    if isinstance(a, date) and isinstance(b, date) and op == "-":
        if isinstance(a, datetime) or isinstance(b, datetime):
            da = a if isinstance(a, datetime) else datetime(a.year, a.month, a.day)
            db = b if isinstance(b, datetime) else datetime(b.year, b.month, b.day)
            return (da - db).total_seconds() / 86400
        return (a - b).days
    if op == "+" and isinstance(a, str) and isinstance(b, str):
        return a + b
    na, nb = _num(a), _num(b)
    if na is None or nb is None:
        return None
    if op == "+":
        return na + nb
    if op == "-":
        return na - nb
    if op == "*":
        return na * nb
    if op == "/":
        return None if nb == 0 else na / nb
    if op == "^":
        return na ** nb
    return None


def _eval(node, rec: dict) -> Any:
    kind = node[0]
    if kind == "lit":
        return node[1]
    if kind == "field":
        return get_path(rec, node[1])
    if kind == "un":
        v = _eval(node[2], rec)
        if node[1] == "!":
            return not _truth(v)
        n = _num(v)
        return None if n is None else (-n if node[1] == "-" else n)
    if kind == "op":
        op = node[1]
        if op == "&&":
            return _truth(_eval(node[2], rec)) and _truth(_eval(node[3], rec))
        if op == "||":
            return _truth(_eval(node[2], rec)) or _truth(_eval(node[3], rec))
        a, b = _eval(node[2], rec), _eval(node[3], rec)
        if op in ("=", "==", "!=", "<>", "<", ">", "<=", ">="):
            return _compare(op, a, b)
        return _arith(op, a, b)
    return _call(node[1], node[2], rec)


def _call(name: str, args: list, rec: dict) -> Any:
    ev = lambda i: _eval(args[i], rec)  # noqa: E731
    n = len(args)
    if name == "AND":
        return all(_truth(ev(i)) for i in range(n))
    if name == "OR":
        return any(_truth(ev(i)) for i in range(n))
    if name == "NOT":
        return not _truth(ev(0))
    if name == "IF":
        return ev(1) if _truth(ev(0)) else ev(2)
    if name == "CASE":
        v = ev(0)
        for i in range(1, n - 1, 2):
            if _compare("=", v, ev(i)):
                return ev(i + 1)
        return ev(n - 1) if n % 2 == 0 else None
    if name in ("ISBLANK", "ISNULL"):
        return _blank(ev(0))
    if name in ("BLANKVALUE", "NULLVALUE"):
        v = ev(0)
        return ev(1) if _blank(v) else v
    if name == "ISPICKVAL":
        return _text(ev(0)) == _text(ev(1))
    if name == "TEXT":
        return _text(ev(0))
    if name == "LEN":
        return len(_text(ev(0)))
    if name == "BEGINS":
        return _text(ev(0)).startswith(_text(ev(1)))
    if name == "CONTAINS":
        return _text(ev(1)) in _text(ev(0))
    if name == "FIND":
        return _text(ev(1)).find(_text(ev(0))) + 1
    if name == "INCLUDES":
        return _text(ev(1)) in [p.strip() for p in _text(ev(0)).split(";")]
    if name == "REGEX":
        try:
            return re.fullmatch(_text(ev(1)), _text(ev(0))) is not None
        except re.error:
            raise Unsupported("its REGEX pattern can't be checked here") from None
    if name == "ISNUMBER":
        return _num(_text(ev(0))) is not None
    if name == "VALUE":
        return _num(ev(0))
    if name == "UPPER":
        return _text(ev(0)).upper()
    if name == "LOWER":
        return _text(ev(0)).lower()
    if name == "TRIM":
        return _text(ev(0)).strip()
    if name == "LEFT":
        return _text(ev(0))[: int(_num(ev(1)) or 0)]
    if name == "RIGHT":
        k = int(_num(ev(1)) or 0)
        return _text(ev(0))[-k:] if k > 0 else ""
    if name == "MID":
        s, start, k = _text(ev(0)), int(_num(ev(1)) or 1), int(_num(ev(2)) or 0)
        return s[start - 1:start - 1 + k]
    if name == "SUBSTITUTE":
        return _text(ev(0)).replace(_text(ev(1)), _text(ev(2)))
    if name == "TODAY":
        return date.today()
    if name == "NOW":
        return datetime.utcnow()
    if name == "DATEVALUE":
        v = ev(0)
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        try:
            return date.fromisoformat(_text(v)[:10])
        except ValueError:
            return None
    if name == "DATE":
        try:
            return date(int(_num(ev(0))), int(_num(ev(1))), int(_num(ev(2))))
        except (TypeError, ValueError):
            return None
    if name in ("YEAR", "MONTH", "DAY"):
        v = ev(0)
        return getattr(v, name.lower()) if isinstance(v, date) else None
    if name in ("ABS", "FLOOR", "CEILING"):
        v = _num(ev(0))
        return None if v is None else {"ABS": abs, "FLOOR": math.floor, "CEILING": math.ceil}[name](v)
    if name in ("MAX", "MIN"):
        vals = [x for x in (_num(ev(i)) for i in range(n)) if x is not None]
        return (max if name == "MAX" else min)(vals) if vals else None
    if name == "ROUND":
        v = _num(ev(0))
        return None if v is None else round(v, int(_num(ev(1)) or 0) if n > 1 else 0)
    if name in ("ISNEW", "ISCHANGED", "ISCLONE"):
        return False  # an existing record being saved again
    if name == "PRIORVALUE":
        return ev(0)
    raise Unsupported(f"uses {name}()")
