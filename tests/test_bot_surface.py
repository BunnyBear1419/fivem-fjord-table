import ast
from pathlib import Path


def _commands(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        for decorator in getattr(node, "decorator_list", []):
            if not (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)):
                continue
            tree_attr = decorator.func.value
            if (
                isinstance(tree_attr, ast.Attribute)
                and isinstance(tree_attr.value, ast.Name)
                and tree_attr.value.id == "bot"
                and tree_attr.attr == "tree"
                and decorator.func.attr == "command"
                and isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
            ):
                for kw in decorator.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                        found.append(kw.value.value)
    return found


def test_public_command_surface_is_private_crafting_directory_only():
    assert _commands("bot.py") == ["crafting"]
