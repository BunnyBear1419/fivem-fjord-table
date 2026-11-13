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


def test_public_command_surface_includes_help_search_stats_and_reports():
    assert _commands("bot.py") == [
        "crafting",
        "crafting-search",
        "crafting-help",
        "crafting-stats",
        "crafting-report",
    ]


def test_admin_group_is_registered_and_permission_gated():
    source = Path("bot.py").read_text(encoding="utf-8")
    assert 'Group(name="crafting-admin"' in source
    assert "default_permissions(manage_guild=True)" in source
    assert "is_guild_admin(interaction)" in source
    for name in ("add-table", "add-recipe", "edit-recipe", "remove-recipe", "backup", "export", "stats", "reports", "resolve-report"):
        assert f'name="{name}"' in source
