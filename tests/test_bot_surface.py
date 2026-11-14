import ast
import json
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
    for feature in ("Browse recipes", "Search recipes", "Find ingredient across tables", "All ingredients", "Recipe shopping list", "Crafting table comparison", "Help and instructions", "Report a recipe issue", "Admin tools"):
        assert feature in source
    for action in ("add_table", "add_recipe", "edit_recipe", "remove_recipe", "backup", "export", "export_csv", "export_xlsx", "validate", "history", "restore_history", "stats", "reports", "resolve_report"):
        assert f'"{action}"' in source
    assert "Manage Server permission or an approved crafting staff role" in source



def test_saved_inventory_and_selectable_spelling_matches_are_wired_into_private_menu():
    source = Path("bot.py").read_text(encoding="utf-8")
    assert 'value="inventory_tracker"' in source
    assert "class InventoryTrackerView" in source
    assert "class SaveInventoryModal" in source
    assert "class CheckSavedInventoryModal" in source
    assert "INVENTORIES_FILE = BASE_DIR / \"inventories.json\"" in source
    assert "str(guild_id or \"dm\"), str(user_id)" in source
    assert "class ChatRecipeMatchView" in source
    assert "Choose the closest recipe match" in source
    assert "record_usage(\"no_result\", query)" in source
    assert "Searches needing better matches" in Path("enhancements.py").read_text(encoding="utf-8")



def test_runtime_player_inventory_data_is_ignored_by_git():
    ignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "inventories.json" in ignore



def test_saved_inventory_and_production_cost_planner_are_exposed_in_menu():
    source = Path("bot.py").read_text(encoding="utf-8")
    assert 'value="inventory_tracker"' in source
    assert 'value="production_cost"' in source
    assert "class ProductionCostModal" in source
    assert "class InventoryTrackerView" in source
    assert "class ChatRecipeMatchView" in source


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



def test_recipe_data_has_no_exact_duplicate_recipe_records():
    data = json.loads(Path("recipes.json").read_text(encoding="utf-8"))
    for table in data["tables"]:
        fingerprints = [
            json.dumps(recipe, ensure_ascii=False, sort_keys=True)
            for recipe in table.get("recipes", [])
        ]
        assert len(fingerprints) == len(set(fingerprints)), table["name"]


def test_duplicate_ingredients_inside_a_recipe_are_not_normalized_away():
    source = Path("crafting.py").read_text(encoding="utf-8")
    assert "def remove_exact_duplicate_recipes(" in source
    assert "Duplicate ingredients inside a recipe are deliberately preserved." in source
    assert "table[\"recipes\"] = unique_recipes" in source



def test_ingredient_lookup_shows_where_item_is_made_and_used():
    source = Path("crafting.py").read_text(encoding="utf-8")
    assert "def find_exact_recipe_outputs(" in source
    assert "Where {ingredient_name.strip()[:80]} is made" in source
    assert "Used at: {group['table']}" in source
    assert "Requires: {ingredients}" in source



def test_all_ingredients_menu_has_downloadable_document():
    source = Path("bot.py").read_text(encoding="utf-8")
    assert 'value="all_ingredients"' in source
    assert "IngredientDirectoryView" in source
    assert "Download full list" in source
    assert "fivem-all-ingredients-directory.txt" in source


def test_ingredient_directory_preserves_exact_names_and_duplicate_entries():
    from crafting import build_ingredient_directory, ingredient_directory_document

    data = {"tables": [{"name": "Test Table", "recipes": [
        {"name": "Test Recipe", "ingredients": [["Coca Leaf", 1], ["Coca Leaves", 2], ["Coca Leaf", 3]]}
    ]}]}
    directory = build_ingredient_directory(data)
    by_name = {item["ingredient"]: item["uses"] for item in directory}
    assert set(by_name) == {"Coca Leaf", "Coca Leaves"}
    assert len(by_name["Coca Leaf"]) == 2
    assert [use["quantity"] for use in by_name["Coca Leaf"]] == [1, 3]
    document = ingredient_directory_document(data)
    assert "Coca Leaf" in document and "Coca Leaves" in document
    assert document.count("requires ×") == 3


def test_production_hardening_uses_atomic_storage_and_bounded_logs():
    source = Path("bot.py").read_text(encoding="utf-8")
    storage = Path("storage.py").read_text(encoding="utf-8")
    crafting = Path("crafting.py").read_text(encoding="utf-8")
    assert "RotatingFileHandler" in source
    assert "class SafeView" in source and "class SafeModal" in source
    assert "recipe_fingerprint" in source and "base_fingerprint" in source
    assert "atomic_write_json" in storage
    assert "os.replace(temp_name, path)" in storage
    assert "original file was preserved" in storage
    assert "atomic_write_json(OVERRIDE_FILE, data)" in crafting


def test_discloud_bundle_and_ci_compile_include_storage_module():
    deploy = Path(".github/workflows/discloud-deploy.yml").read_text(encoding="utf-8")
    tests = Path(".github/workflows/tests.yml").read_text(encoding="utf-8")
    assert "enhancements.py storage.py recipes.json" in deploy
    assert "enhancements.py storage.py" in tests


def test_admin_menu_has_a_backup_download_path():
    source = Path("bot.py").read_text(encoding="utf-8")
    assert 'value="download_backup"' in source
    assert "crafting-backup-*.json" in source
    assert "keep an external copy outside Discloud" in source


def test_browse_view_paginates_tables_and_recipes_within_discord_select_limits():
    source = Path("crafting.py").read_text(encoding="utf-8")
    assert "table_start = self.table_page * 25" in source
    assert "self.tables[table_start:table_start + 25]" in source
    assert "self._previous_table_page" in source
    assert "self._next_table_page" in source
