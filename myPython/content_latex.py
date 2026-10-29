#!/usr/bin/env python3
"""
content_latex.py - show, in colour, what should be fixed in the LaTeX of a Hugo page.

    from content_latex import check_latex
    check_latex(Path("/Volumes/MacDatosMaster/justtothepoint/content/calculus/thedivergenceth2.md"))

It NEVER writes or creates anything. It reads the page and prints (with Rich) only the
lines that need a fix: the line number, then the line as it should be, with every new
or corrected expression in RED and the rest of the text in the normal colour.

    12  This is my bla... bla... bla $3^2$ morebla...
                                     ^^^^ red

What it recognises (everywhere except front matter, fenced code, `inline code`,
link/URL targets, shortcodes and HTML tags):

  prose                          becomes
  -----------------------------  -------------------------------------------
  π  θ  ∇·F  ∫  ≤  ∞  ½ ...     $\\pi$  $\\theta$  $\\nabla\\cdot F$  ...  $\\frac{1}{2}$
  u²   x₁   R³                   $u^2$   $x_1$   $\\mathbb{R}^3$ (ℝ³)
  3<sup>2     3<sup>2</sup>      $3^2$
  x<sub>i</sub>                  $x_i$
  <sup>1</sup>&frasl;<sub>2</sub>  $\\frac{1}{2}$      (a digit glued before it is kept: 1½)
  1&frasl;2                      $\\frac{1}{2}$
  x^2   2^10   e^-x             $x^2$   $2^{10}$   $e^{-x}$
  \\alpha  \\vec{F}  \\sin        wrapped in $...$
  sin(x)   ln(2)   cos θ        $\\sin(x)$   $\\ln(2)$   $\\cos \\theta$
  \\vert\\begin{smallmatrix}..\\end{smallmatrix}\\vert   $\\begin{vmatrix}..\\end{vmatrix}$

  inside math you already wrote ($...$, $$...$$, also over several lines):
  sin cos tan ln ... -> \\sin \\cos \\tan \\ln, ysin(z) -> y\\sin(z), Unicode -> LaTeX,
  u² -> u^2, ⟨a,b⟩ -> \\langle a,b\\rangle, x^10 -> x^{10}, smallmatrix+bars -> vmatrix.
  Only the changed pieces are red; the rest of your math is left as it was.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    from rich.console import Console
    from rich.text import Text
except ImportError:  # pragma: no cover
    sys.exit("content_latex.py needs Rich:  python3 -m pip install rich")

# ============================================================================
# Look & feel  (edit freely)
# ============================================================================
NEW_STYLE = "bold red"  # new / corrected expressions
TEXT_STYLE = (
    ""  # "" = your terminal's normal text colour (use "black" on a white background)
)
LINENO_STYLE = "dim cyan"  # the line numbers
WARN_STYLE = "yellow"  # lines with an unpaired $ (shown as they are, with a ?)
CONVERT_U_TAG_EXPONENT = True  # x<u>2</u>  ->  x^2

console = Console(highlight=False)

# ============================================================================
# Symbol tables  (edit freely)
# ============================================================================
GREEK = {
    "α": r"\alpha",
    "β": r"\beta",
    "γ": r"\gamma",
    "δ": r"\delta",
    "ε": r"\epsilon",
    "ϵ": r"\varepsilon",
    "ζ": r"\zeta",
    "η": r"\eta",
    "θ": r"\theta",
    "ϑ": r"\vartheta",
    "ι": r"\iota",
    "κ": r"\kappa",
    "λ": r"\lambda",
    "μ": r"\mu",
    "ν": r"\nu",
    "ξ": r"\xi",
    "π": r"\pi",
    "ϖ": r"\varpi",
    "ρ": r"\rho",
    "ϱ": r"\varrho",
    "σ": r"\sigma",
    "ς": r"\varsigma",
    "τ": r"\tau",
    "υ": r"\upsilon",
    "φ": r"\phi",
    "ϕ": r"\varphi",
    "χ": r"\chi",
    "ψ": r"\psi",
    "ω": r"\omega",
    "Γ": r"\Gamma",
    "Δ": r"\Delta",
    "Θ": r"\Theta",
    "Λ": r"\Lambda",
    "Ξ": r"\Xi",
    "Π": r"\Pi",
    "Σ": r"\Sigma",
    "Υ": r"\Upsilon",
    "Φ": r"\Phi",
    "Ψ": r"\Psi",
    "Ω": r"\Omega",
}
VULGAR = {
    "½": r"\frac{1}{2}",
    "⅓": r"\frac{1}{3}",
    "⅔": r"\frac{2}{3}",
    "¼": r"\frac{1}{4}",
    "¾": r"\frac{3}{4}",
    "⅕": r"\frac{1}{5}",
    "⅖": r"\frac{2}{5}",
    "⅗": r"\frac{3}{5}",
    "⅘": r"\frac{4}{5}",
    "⅙": r"\frac{1}{6}",
    "⅚": r"\frac{5}{6}",
    "⅛": r"\frac{1}{8}",
    "⅜": r"\frac{3}{8}",
    "⅝": r"\frac{5}{8}",
    "⅞": r"\frac{7}{8}",
}
# "Strong": a word containing one of these is wrapped in $...$ when it is in plain prose.
STRONG_SYMBOLS = {
    "∇": r"\nabla",
    "∂": r"\partial",
    "∫": r"\int",
    "∬": r"\iint",
    "∭": r"\iiint",
    "∮": r"\oint",
    "∑": r"\sum",
    "∏": r"\prod",
    "∞": r"\infty",
    "≤": r"\leq",
    "≥": r"\geq",
    "≠": r"\neq",
    "≈": r"\approx",
    "≡": r"\equiv",
    "≪": r"\ll",
    "≫": r"\gg",
    "∼": r"\sim",
    "≅": r"\cong",
    "∝": r"\propto",
    "∈": r"\in",
    "∉": r"\notin",
    "⊂": r"\subset",
    "⊆": r"\subseteq",
    "⊃": r"\supset",
    "⊇": r"\supseteq",
    "∪": r"\cup",
    "∩": r"\cap",
    "∅": r"\emptyset",
    "∀": r"\forall",
    "∃": r"\exists",
    "∥": r"\parallel",
    "⊥": r"\perp",
    "∠": r"\angle",
    "⇒": r"\Rightarrow",
    "⇔": r"\Leftrightarrow",
    "⇐": r"\Leftarrow",
    "ℝ": r"\mathbb{R}",
    "ℕ": r"\mathbb{N}",
    "ℤ": r"\mathbb{Z}",
    "ℚ": r"\mathbb{Q}",
    "ℂ": r"\mathbb{C}",
    "ℓ": r"\ell",
    "ℏ": r"\hbar",
    "ℵ": r"\aleph",
}
# "Weak": converted inside math / inside a word that already has a strong symbol,
# but they do not trigger anything on their own (they are normal punctuation).
WEAK_SYMBOLS = {
    "·": r"\cdot",
    "⋅": r"\cdot",
    "∙": r"\cdot",
    "×": r"\times",
    "÷": r"\div",
    "±": r"\pm",
    "∓": r"\mp",
    "→": r"\to",
    "←": r"\leftarrow",
    "↔": r"\leftrightarrow",
    "↦": r"\mapsto",
    "−": "-",
    "°": r"^\circ",
    "…": r"\dots",
    "⋯": r"\cdots",
    "′": "'",
    "″": "''",
    "µ": r"\mu",
    "⟨": r"\langle",
    "⟩": r"\rangle",
    "⌊": r"\lfloor",
    "⌋": r"\rfloor",
    "⌈": r"\lceil",
    "⌉": r"\rceil",
}
SUPERSCRIPTS = {
    "⁰": "0",
    "¹": "1",
    "²": "2",
    "³": "3",
    "⁴": "4",
    "⁵": "5",
    "⁶": "6",
    "⁷": "7",
    "⁸": "8",
    "⁹": "9",
    "⁺": "+",
    "⁻": "-",
    "ⁿ": "n",
    "ⁱ": "i",
}
SUBSCRIPTS = {
    "₀": "0",
    "₁": "1",
    "₂": "2",
    "₃": "3",
    "₄": "4",
    "₅": "5",
    "₆": "6",
    "₇": "7",
    "₈": "8",
    "₉": "9",
    "₊": "+",
    "₋": "-",
    "ₙ": "n",
    "ᵢ": "i",
    "ⱼ": "j",
    "ₐ": "a",
    "ₑ": "e",
    "ₒ": "o",
    "ₓ": "x",
    "ₖ": "k",
    "ₘ": "m",
    "ₚ": "p",
    "ₛ": "s",
    "ₜ": "t",
}
FUNCS = (
    "arcsin",
    "arccos",
    "arctan",
    "sinh",
    "cosh",
    "tanh",
    "coth",
    "sin",
    "cos",
    "tan",
    "cot",
    "sec",
    "csc",
    "ln",
    "log",
    "exp",
    "lim",
    "det",
    "max",
    "min",
)
PROSE_FUNCS = tuple(
    f for f in FUNCS if f not in ("max", "min")
)  # too ambiguous in prose
_TRIG = {"sin", "cos", "tan", "cot", "sec", "csc", "sinh", "cosh", "tanh", "coth"}

# ============================================================================
# Derived data
# ============================================================================
SYMBOL_TO_LATEX = {**GREEK, **VULGAR, **STRONG_SYMBOLS, **WEAK_SYMBOLS}
STRONG_CHARS = (
    set(GREEK)
    | set(VULGAR)
    | set(STRONG_SYMBOLS)
    | set(SUPERSCRIPTS)
    | set(SUBSCRIPTS)
    | {"√"}
)
ALL_MATH_CHARS = STRONG_CHARS | set(WEAK_SYMBOLS)
SUPSUB_CHARS = set(SUPERSCRIPTS) | set(SUBSCRIPTS)
_GREEK_CLASS = "[" + "".join(GREEK) + "]"
_MATHCHAR_CLASS = "[" + re.escape("".join(sorted(ALL_MATH_CHARS))) + "]"
_FUNC_ALT = "|".join(sorted(FUNCS, key=len, reverse=True))

# Binary operators / relations: printed with a space on both sides.
_SPACED = {SYMBOL_TO_LATEX[ch] for ch in "·⋅∙×÷±∓→←↔↦≤≥≠≈≡≪≫∼≅∝∈∉⊂⊆⊃⊇∪∩⇒⇔⇐∥⊥"}

# Marks: everything between S and E is "new" (printed in red). They may nest.
S, E = "\ue000", "\ue001"


def _m(x: str) -> str:
    return S + x + E


def _strip(s: str) -> str:
    return s.replace(S, "").replace(E, "")


def _split_marked(s: str):
    """[(is_new, text), ...]  -  nesting flattened."""
    out, buf, depth = [], [], 0
    for ch in s:
        if ch in (S, E):
            if buf:
                out.append((depth > 0, "".join(buf)))
                buf = []
            depth = max(0, depth + (1 if ch == S else -1))
        else:
            buf.append(ch)
    if buf:
        out.append((depth > 0, "".join(buf)))
    return out


_KNOWN_CMDS = (
    {v[1:] for v in SYMBOL_TO_LATEX.values() if re.fullmatch(r"\\[A-Za-z]+", v)}
    | set(FUNCS)
    | {
        "frac",
        "vec",
        "hat",
        "bar",
        "tilde",
        "dot",
        "ddot",
        "sqrt",
        "ldots",
        "mathbb",
        "mathbf",
        "mathrm",
        "left",
        "right",
        "iff",
        "implies",
        "lim",
        "to",
    }
)
_CMD_RE = re.compile(r"\\([A-Za-z]+)")
_CARET_RE = re.compile(r"[A-Za-z0-9)\]}]\^(?:\{[^{}]+\}|[A-Za-z0-9+\-]+)")
_SUBBRACE_RE = re.compile(r"[A-Za-z0-9)\]}]_\{[^{}]+\}")

# ============================================================================
# 1. Repairing math (the content between the dollars)
# ============================================================================
_FRAC_TAG = re.compile(
    r"<sup>\s*([^<>]{1,12}?)\s*</sup>\s*(?:&frasl;|&#8260;|&#x2044;|⁄|/)\s*<sub>\s*([^<>]{1,12}?)\s*</sub>",
    re.I,
)
_SUP_TAG = re.compile(r"<sup>\s*([^<>\n]{1,20}?)\s*</sup>", re.I)
_SUB_TAG = re.compile(r"<sub>\s*([^<>\n]{1,20}?)\s*</sub>", re.I)

_PROTECTED_CMD_RE = re.compile(
    r"\\(?:text|textbf|textit|textrm|textsf|texttt|mathrm|mathit|mathbf|mathsf|mathtt|"
    r"operatorname|mbox|hbox|label|tag|href|url|begin|end|color|class|style|cssId|ref|eqref)"
    r"\s*\{(?:[^{}]|\{[^{}]*\})*\}"
)

_VMATRIX_RE = re.compile(
    r"(?P<l>\\vert|\\lvert|\\left\s*\\vert|\\left\s*\||\|)\s*"
    r"\\begin\{(?P<env>smallmatrix|matrix)\}(?P<body>.*?)\\end\{(?P=env)\}\s*"
    r"(?P<r>\\vert|\\rvert|\\right\s*\\vert|\\right\s*\||\|)",
    re.S,
)
_VMATRIX_PAIRS = {
    ("\\vert", "\\vert"),
    ("\\lvert", "\\rvert"),
    ("|", "|"),
    ("\\vert", "|"),
    ("|", "\\vert"),
    ("\\left\\vert", "\\right\\vert"),
    ("\\left|", "\\right|"),
}
_DBL_VMATRIX_RE = re.compile(
    r"\\Vert\s*\\begin\{(?P<env>smallmatrix|matrix)\}(?P<body>.*?)\\end\{(?P=env)\}\s*\\Vert",
    re.S,
)

_GLUED_RE = re.compile(r"(?<![\\A-Za-z])([A-Za-z])(" + _FUNC_ALT + r")(?=\()")
_FUNC_RE = re.compile(r"(?<![\\A-Za-z])(" + _FUNC_ALT + r")(?![A-Za-z])")
_BAD_EXP_RE = re.compile(r"(?<!\\)\^(-?\d{2,}|-\d|-[A-Za-z])")  # x^10  e^-x   -> braces
_BAD_SUB_RE = re.compile(r"(?<!\\)_(\d{2,})")  # x_10          -> x_{10}


def _vmatrix_sub(m: re.Match) -> str:
    pair = (re.sub(r"\s+", "", m.group("l")), re.sub(r"\s+", "", m.group("r")))
    if pair in _VMATRIX_PAIRS:
        return _m(r"\begin{vmatrix}") + m.group("body") + _m(r"\end{vmatrix}")
    return m.group(0)


def _unicode_to_latex(s: str) -> str:
    out, i, n = [], 0, len(s)

    def tail() -> str:
        return _strip(out[-1])[-1:] if out else ""

    while i < n:
        c = s[i]
        if c in SUPERSCRIPTS or c in SUBSCRIPTS:
            table, mark = (
                (SUPERSCRIPTS, "^") if c in SUPERSCRIPTS else (SUBSCRIPTS, "_")
            )
            j = i
            while j < n and s[j] in table:
                j += 1
            run = "".join(table[x] for x in s[i:j])
            if tail() in ("^", "_"):
                out.append(_m("{" + run + "}"))
            elif len(run) == 1 and run not in "+-":
                out.append(_m(mark + run))
            else:
                out.append(_m(mark + "{" + run + "}"))
            i = j
        elif c == "√":
            rest = s[i + 1 :]
            m = re.match(r"\(((?:[^()]|\([^()]*\))*)\)", rest)
            if m:
                out.append(_m(r"\sqrt{" + _unicode_to_latex(m.group(1)) + "}"))
                i += 1 + m.end()
                continue
            m = re.match(
                r"(?:\d+(?:\.\d+)?|[A-Za-z]|\\[A-Za-z]+|"
                + _GREEK_CLASS
                + r")[⁰¹²³⁴⁵⁶⁷⁸⁹]*",
                rest,
            )
            if m:
                out.append(_m(r"\sqrt{" + _unicode_to_latex(m.group(0)) + "}"))
                i += 1 + m.end()
                continue
            out.append(_m(r"\surd"))
            i += 1
        elif c in SYMBOL_TO_LATEX:
            rep = SYMBOL_TO_LATEX[c]
            prv, nxt = s[i - 1 : i] if i else "", s[i + 1 : i + 2]
            if rep in _SPACED:  # k·∇  ->  k \cdot \nabla
                if prv and not prv.isspace() and prv not in "({[":
                    rep = " " + rep
                if nxt and not nxt.isspace() and nxt not in ")}]":
                    rep += " "
            elif rep[-1:].isalpha() and nxt.isascii() and nxt.isalpha():
                rep += " "
            out.append(_m(rep))
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def fix_math(s: str) -> str:
    """Repair the CONTENT of a math span. Changed pieces come back wrapped in marks."""
    s = _FRAC_TAG.sub(lambda m: _m("\\frac{" + m[1] + "}{" + m[2] + "}"), s)
    s = _SUP_TAG.sub(lambda m: _m("^{" + m[1] + "}"), s)
    s = _SUB_TAG.sub(lambda m: _m("_{" + m[1] + "}"), s)
    s = _VMATRIX_RE.sub(_vmatrix_sub, s)
    s = _DBL_VMATRIX_RE.sub(
        lambda m: _m(r"\begin{Vmatrix}") + m["body"] + _m(r"\end{Vmatrix}"), s
    )
    parts, pos = [], 0
    for m in _PROTECTED_CMD_RE.finditer(s):
        parts.append((False, s[pos : m.start()]))
        parts.append((True, m.group(0)))
        pos = m.end()
    parts.append((False, s[pos:]))
    res = []
    for protected, piece in parts:
        if protected or not piece:
            res.append(piece)
            continue
        piece = _unicode_to_latex(piece)
        piece = _BAD_EXP_RE.sub(lambda m: _m("^{" + m[1] + "}"), piece)
        piece = _BAD_SUB_RE.sub(lambda m: _m("_{" + m[1] + "}"), piece)
        piece = _GLUED_RE.sub(
            lambda m: (
                m.group(0)
                if (m[1] in "aA" and m[2] in _TRIG)
                else m[1] + _m("\\" + m[2])
            ),
            piece,
        )
        piece = _FUNC_RE.sub(lambda m: _m("\\" + m[1]), piece)
        res.append(piece)
    return "".join(res)


# ============================================================================
# 2. Plain prose: wrap "math words" in $...$
# ============================================================================
_SUPB = r"(?<![A-Za-z0-9])(?P<b>\d+|[A-Za-z]|\)|\])"
_FRAC_PROSE = re.compile(
    r"(?<![A-Za-z0-9])(?P<pre>\d+)?(?i:<sup>)\s*(?P<n>[^<>\s]{1,10}?)\s*(?i:</sup>)\s*"
    r"(?:&frasl;|&#8260;|&#x2044;|⁄|/)\s*(?i:<sub>)\s*(?P<d>[^<>\s]{1,10}?)\s*(?i:</sub>)"
)
_FRAC_ENTITY = re.compile(
    r"(?<![A-Za-z0-9])(\d+)(?:&frasl;|&#8260;|&#x2044;|⁄)(\d+)(?![A-Za-z0-9])"
)
_SUP_CLOSED = re.compile(_SUPB + r"(?i:<sup>)\s*(?P<e>[^<>\s]{1,12}?)\s*(?i:</sup>)")
_SUP_OPEN = re.compile(
    _SUPB + r"(?i:<sup>)\s*(?P<e>[+\-−]?\d{1,3}|[A-Za-z])(?![A-Za-z0-9])"
)
_SUB_CLOSED = re.compile(
    r"(?<![A-Za-z0-9])(?P<b>[a-z]|\))(?i:<sub>)\s*(?P<e>[^<>\s]{1,12}?)\s*(?i:</sub>)"
)
_SUB_OPEN = re.compile(
    r"(?<![A-Za-z0-9])(?P<b>[a-z]|\))(?i:<sub>)\s*(?P<e>\d{1,3}|[a-z])(?![A-Za-z0-9])"
)
_U_TAG = re.compile(_SUPB + r"<u>(?P<e>[+\-]?\d{1,2}|[A-Za-z])</u>")
_ORDINALS = {"st", "nd", "rd", "th"}


def _script(mark: str):
    def sub(m: re.Match) -> str:
        e = m["e"].replace("−", "-")
        if e.lower() in _ORDINALS:  # 1<sup>st</sup>
            return m.group(0)
        if mark == "^" and re.fullmatch(r"[0-9A-Za-z]", e):
            return m["b"] + "^" + e
        return m["b"] + mark + "{" + e + "}"

    return sub


def _rewrite_tags(text: str) -> str:
    text = _FRAC_PROSE.sub(
        lambda m: (m["pre"] or "") + "\\frac{" + m["n"] + "}{" + m["d"] + "}", text
    )
    text = _FRAC_ENTITY.sub(lambda m: "\\frac{" + m[1] + "}{" + m[2] + "}", text)
    text = _SUP_CLOSED.sub(_script("^"), text)
    text = _SUP_OPEN.sub(_script("^"), text)
    text = _SUB_CLOSED.sub(_script("_"), text)
    text = _SUB_OPEN.sub(_script("_"), text)
    if CONVERT_U_TAG_EXPONENT:
        text = _U_TAG.sub(_script("^"), text)
    return text


_LEAD_STRIP = '"*_~“‘«'
_TRAIL_STRIP = '.,;:!?"*_~”’»'
_PAIRS = {"(": ")", "[": "]", "{": "}"}
_OPS = {"+": "+", "-": "-", "=": "=", "<": "<", ">": ">", "/": "/"}
_NUM_RE = re.compile(r"^(\d+(?:[.,]\d+)?)([.,;:!?]*)$")


def _split_token(tok: str):
    lead, core, trail = "", tok, ""
    changed = True
    while changed and core:
        changed = False
        if core[0] in _LEAD_STRIP:
            lead, core, changed = lead + core[0], core[1:], True
        elif core[-1] in _TRAIL_STRIP:
            trail, core, changed = core[-1] + trail, core[:-1], True
        elif core[0] in _PAIRS and core.count(core[0]) > core.count(_PAIRS[core[0]]):
            lead, core, changed = lead + core[0], core[1:], True
        elif core[-1] in _PAIRS.values():
            opener = next(k for k, v in _PAIRS.items() if v == core[-1])
            if core.count(core[-1]) > core.count(opener):
                trail, core, changed = core[-1] + trail, core[:-1], True
    return lead, core, trail


class _Item:
    __slots__ = ("kind", "s", "lead", "latex", "trail")

    def __init__(self, kind, s="", lead="", latex="", trail=""):
        self.kind, self.s, self.lead, self.latex, self.trail = (
            kind,
            s,
            lead,
            latex,
            trail,
        )


def _mathy(core: str) -> bool:
    if any(ch in STRONG_CHARS for ch in core):
        return True
    if _CARET_RE.search(core) or _SUBBRACE_RE.search(core):
        return True
    return any(m.group(1) in _KNOWN_CMDS for m in _CMD_RE.finditer(core))


def _convert_token(tok: str):
    """Pieces for one whitespace-free word, or None when it is not math."""
    lead, core, trail = _split_token(_rewrite_tags(tok))
    if not core or not _mathy(core):
        return None
    if all(ch in SUPSUB_CHARS for ch in core):  # lone ² or ₁ (footnote-like)
        return None
    if any(
        "\u0370" <= ch <= "\u03ff" and ch not in GREEK for ch in core
    ):  # real Greek text
        return None
    if re.search(_GREEK_CLASS + "{3,}", core):
        return None
    words = re.findall(r"(?<![\\A-Za-z])[A-Za-z]{3,}", re.sub(r"\\[A-Za-z]+", "", core))
    if any(w not in FUNCS for w in words):
        # e.g. "θ-dependent": wrap only the symbol clusters
        pat = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]?" + _MATHCHAR_CLASS + "+")
        pieces, p = ([_Item("text", s=lead)] if lead else []), 0
        for m in pat.finditer(core):
            if not any(ch in STRONG_CHARS for ch in m.group(0)):
                continue
            pieces.append(_Item("text", s=core[p : m.start()]))
            pieces.append(_Item("math", latex=_strip(fix_math(m.group(0)))))
            p = m.end()
        if p == 0:
            return None
        pieces.append(_Item("text", s=core[p:] + trail))
        return [x for x in pieces if x.kind == "math" or x.s]
    return [_Item("math", lead=lead, latex=_strip(fix_math(core)), trail=trail)]


def _merge_items(items):
    """cos θ -> one span;   x² + y² = 1 -> one span."""
    out, i, n = [], 0, len(items)
    while i < n:
        it = items[i]
        if (
            it.kind == "text"
            and it.s in PROSE_FUNCS
            and i + 2 < n
            and items[i + 1].kind == "ws"
            and items[i + 1].s == " "
            and items[i + 2].kind == "math"
            and not items[i + 2].lead
        ):
            m = items[i + 2]
            it = _Item("math", latex="\\" + it.s + " " + m.latex, trail=m.trail)
            i += 2
        if it.kind == "math":
            while (
                it.trail == ""
                and i + 4 < n
                and items[i + 1].kind == "ws"
                and items[i + 1].s == " "
                and items[i + 2].kind == "text"
                and items[i + 2].s in _OPS
                and items[i + 3].kind == "ws"
                and items[i + 3].s == " "
            ):
                nxt, op = items[i + 4], _OPS[items[i + 2].s]
                if nxt.kind == "math" and not nxt.lead:
                    it = _Item(
                        "math",
                        lead=it.lead,
                        latex=it.latex + " " + op + " " + nxt.latex,
                        trail=nxt.trail,
                    )
                elif nxt.kind == "text" and _NUM_RE.match(nxt.s):
                    num = _NUM_RE.match(nxt.s)
                    it = _Item(
                        "math",
                        lead=it.lead,
                        latex=it.latex + " " + op + " " + num[1],
                        trail=num[2],
                    )
                else:
                    break
                i += 4
        out.append(it)
        i += 1
    return out


_CALL_RE = re.compile(
    r"(?<![A-Za-z0-9_\\.$])(?:"
    + "|".join(sorted(PROSE_FUNCS, key=len, reverse=True))
    + r")\((?:[^()\n$]|\([^()\n$]*\)){1,40}\)"
)


def _calls(marked: str) -> str:
    """sin(x), ln(2) ... in the text that is still plain."""

    def sub(m: re.Match) -> str:
        words = re.findall(r"(?<![\\A-Za-z])[A-Za-z]{2,}", m.group(0))
        if any(w not in FUNCS for w in words):
            return m.group(0)
        return _m("$" + _strip(fix_math(m.group(0))) + "$")

    parts = []
    for is_new, text in _split_marked(marked):
        parts.append(_m(text) if is_new else _CALL_RE.sub(sub, text))
    return "".join(parts)


def _prose(text: str, in_table: bool) -> str:
    if not text.strip():
        return text
    items, pos = [], 0
    for m in re.finditer(r"\S+", text):
        if m.start() > pos:
            items.append(_Item("ws", s=text[pos : m.start()]))
        pos = m.end()
        pieces = (
            None if (in_table and "|" in m.group(0)) else _convert_token(m.group(0))
        )
        items.extend(pieces if pieces else [_Item("text", s=m.group(0))])
    if pos < len(text):
        items.append(_Item("ws", s=text[pos:]))
    parts = []
    for it in _merge_items(items):
        if it.kind == "math":
            parts.append(it.lead + _m("$" + it.latex + "$") + it.trail)
        else:
            parts.append(it.s)
    return _calls("".join(parts))


# ============================================================================
# 3. One line
# ============================================================================
_ENVS = r"(?:small)?matrix|[pbBvV]matrix|cases|array|aligned|split"
_ZONE_RE = re.compile(
    "|".join(
        [
            r"(?P<code>(?<!`)(?P<bt>`+)(?!`).+?(?<!`)(?P=bt)(?!`))",
            r"(?P<esc>\\[$\[\]()])",
            r"(?P<dmath>(?<![\\$])\$\$.+?(?<!\\)\$\$)",
            r"(?P<imath>(?<![\\$])\$(?![\s$]).+?(?<![\s\\])\$(?!\d)"
            r"|(?<![\\$])\$(?![\s$])(?=[^$]*[\\^_{}=]).+?\s+\$(?!\d))",
            r"(?P<env>(?:(?:\\vert|\\lvert|\\Vert|\\left\s*(?:\||\\vert|\\Vert))\s*)?"
            r"\\begin\{(?P<envn>" + _ENVS + r")\}.*?\\end\{(?P=envn)\}"
            r"(?:\s*(?:\\vert|\\rvert|\\Vert|\\right\s*(?:\||\\vert|\\Vert)))?)",
            r"(?P<link>\]\([^)]*\))",
            r"(?P<url>(?:https?|ftp)://[^\s<>)\]]+)",
            r"(?P<shortcode>\{\{[<%].*?[>%]\}\})",
            r"(?P<tag><!--.*?-->|</?(?!(?:sup|sub|u)\b)[A-Za-z][^<>]*>)",
        ]
    ),
    re.I,
)


def _convert_line(line: str, in_display: bool):
    """-> (marked line, still inside a multi-line $$ block?)"""
    marked, display, _ = _convert_line_ex(line, in_display)
    return marked, display


def _convert_line_ex(line: str, in_display: bool):
    """-> (marked line, still inside a multi-line $$ block?, unpaired $ left in prose?)"""
    if in_display:
        idx = line.find("$$")
        if idx == -1:
            return fix_math(line), True, False
        rest, _, stray = _convert_line_ex(line[idx + 2 :], False)
        return fix_math(line[:idx]) + "$$" + rest, False, stray
    in_table = line.lstrip().startswith("|")
    out, pos = [], 0

    stray = False

    def prose(text: str):
        """Plain text; an unmatched $$ opens a multi-line display formula."""
        nonlocal stray
        i = text.find("$$")
        if i == -1:
            stray = stray or "$" in text
            return _prose(text, in_table), False
        stray = stray or "$" in text[:i]
        return _prose(text[:i], in_table) + "$$" + fix_math(text[i + 2 :]), True

    for m in _ZONE_RE.finditer(line):
        text, opened = prose(line[pos : m.start()])
        out.append(text)
        if opened:
            return "".join(out), True, stray
        kind, piece = m.lastgroup, m.group(0)
        if kind == "dmath":
            piece = "$$" + fix_math(piece[2:-2]) + "$$"
        elif kind == "imath":
            inner = piece[1:-1]
            tail = inner[len(inner.rstrip()) :]  # keep "math $" exactly as written
            piece = "$" + fix_math(inner.rstrip()) + tail + "$"
        elif kind == "env":
            piece = _m("$" + _strip(fix_math(piece)) + "$")
        out.append(piece)
        pos = m.end()
    text, opened = prose(line[pos:])
    out.append(text)
    return "".join(out), opened, stray


# ============================================================================
# 4. The only public function
# ============================================================================
_FENCE_RE = re.compile(r"^[ \t>]*(`{3,}|~{3,})")


def _frontmatter_end(lines, text: str) -> int:
    """Number of lines taken by the front matter (0 when there is none)."""
    if not lines:
        return 0
    first = lines[0].lstrip("\ufeff").strip()
    if first in ("---", "+++"):
        for i in range(1, len(lines)):
            if lines[i].strip() == first or (
                first == "---" and lines[i].strip() == "..."
            ):
                return i + 1
        return 0
    if first.startswith("{"):
        try:
            _, end = json.JSONDecoder().raw_decode(text.lstrip("\ufeff"))
            return text.lstrip("\ufeff")[:end].count("\n") + 1
        except ValueError:
            return 0
    return 0


def check_latex(page) -> None:
    """Print (with Rich) every line of the Markdown page that needs a LaTeX fix.

    page: path of the .md file (Path or str).  Nothing is written or returned.
    """
    path = Path(page)
    with open(path, "r", encoding="utf-8", newline="") as fh:
        text = fh.read()
    lines = text.splitlines()
    skip = _frontmatter_end(lines, text)
    fence, display, changed, unsure = None, False, 0, 0

    console.print(Text(str(path), style="bold"))
    for n, line in enumerate(lines, 1):
        if n <= skip:
            continue
        m = _FENCE_RE.match(line)
        if fence:
            if (
                m
                and m.group(1)[0] == fence[0]
                and len(m.group(1)) >= len(fence)
                and not line.lstrip(" \t>")[len(m.group(1)) :].strip()
            ):
                fence = None
            continue
        if m:
            fence = m.group(1)
            continue
        marked, display, stray = _convert_line_ex(line, display)
        if S not in marked:
            continue
        if stray:  # an unpaired $ makes every guess unreliable: show it, do not convert
            console.print(Text(f"{n:>5} ? {line}", style=WARN_STYLE), soft_wrap=True)
            unsure += 1
            continue
        changed += 1
        row = Text()
        row.append(f"{n:>5}  ", style=LINENO_STYLE)
        for is_new, chunk in _split_marked(marked):
            row.append(chunk, style=NEW_STYLE if is_new else TEXT_STYLE)
        console.print(row, soft_wrap=True)
    summary = f"{changed} line(s) to fix" if changed else "nothing to fix"
    if unsure:
        summary += (
            f"   |   {unsure} line(s) marked ? have an unpaired $ - check them by hand"
        )
    console.print(Text(summary, style="dim"))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python3 content_latex.py page.md")
    check_latex(Path(sys.argv[1]))
