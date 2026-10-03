import re
import ast
import operator as op
from app.runtime.registry import tool
from app.intelligence.keywords import CALC_KW, has, other_intent, extract_calculation_expression

_OPS = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv,
        ast.Pow: op.pow, ast.Mod: op.mod, ast.USub: op.neg, ast.UAdd: op.pos}


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("تعبير غير مسموح")


def _match(goal: str) -> bool:
    expression = extract_calculation_expression(goal)
    return bool(expression) and (has(goal, CALC_KW) or re.search(r"\b(?:what is|what\s+is|times|multiply|divide|subtract|add)\b", goal, re.I) or re.search(r"(?:اضرب|اقسم|اطرح|اجمع)", goal)) and not re.search(r"\b(?:weather|time|date|remember|save note)\b", goal, re.I)


@tool(description="يحسب تعبير رياضي", params={"expression": "مثل 5*3+2"}, stage=0, match=_match,
      build_args=lambda g: {"expression": extract_calculation_expression(g)},
      pipe_source=True, pipe_label=lambda a: f"{a['expression']} = ",
      capability="calculate", produces=("calculation_completed",), cost=1.0, risk="low", idempotent=True, parallel_safe=True)
def calculator(expression: str):
    return _eval(ast.parse(expression.replace("^", "**"), mode="eval").body)
