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


def test_only_one_public_slash_command_is_registered():
    assert _commands("bot.py") == ["crafting"]


def test_all_features_are_in_private_dropdown_menus():
    source = Path("bot.py").read_text(encoding="utf-8")
    for feature in ("Browse recipes", "Search recipes", "Find ingredient across tables", "Help and instructions", "Report a recipe issue", "Admin tools"):
        assert feature in source
    for action in ("add_table", "add_recipe", "edit_recipe", "remove_recipe", "backup", "export", "stats", "reports", "resolve_report"):
        assert f'"{action}"' in source
    assert "Manage Server permission is required." in source


def test_legacy_guild_commands_are_cleared_on_ready():
    source = Path("bot.py").read_text(encoding="utf-8")
    assert "self.tree.clear_commands(guild=guild)" in source
    assert "await self.tree.sync(guild=guild)" in source



def test_cross_table_ingredient_lookup_is_exact_name_only():
    source = Path("crafting.py").read_text(encoding="utf-8")
    assert "def find_ingredient_usage(" in source
    assert 'str(name).casefold().strip() == needle' in source
    assert "Coca Leaf and Coca Leaves are treated separately" in source


def test_ingredient_lookup_is_available_from_main_menu():
    source = Path("bot.py").read_text(encoding="utf-8")
    assert 'value="ingredient_lookup"' in source
    assert "IngredientLookupModal" in source
    assert "ingredient_usage_embed(bot.recipe_data, ingredient)" in source
