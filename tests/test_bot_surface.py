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


def test_dashboard_and_information_commands_are_registered_without_role_management_commands():
    commands = set(_commands("bot.py"))
    assert commands == {"dashboard", "crafting", "shops", "locations", "moonshine"}
    assert "setrole" not in commands
    assert "removerole" not in commands


def test_all_features_are_in_private_dropdown_menus():
    source = Path("bot.py").read_text(encoding="utf-8")
    for feature in ("Browse recipes", "Search recipes", "Find ingredient across tables", "All ingredients", "Recipe shopping list", "Crafting table comparison", "Help and instructions", "Report a recipe issue", "Admin tools"):
        assert feature in source
    for action in ("add_table", "add_recipe", "edit_recipe", "remove_recipe", "backup", "export", "export_csv", "export_xlsx", "validate", "history", "restore_history", "stats", "reports", "resolve_report"):
        assert f'"{action}"' in source
    assert "Manage Server permission or an approved crafting staff role" not in source
    assert "Configure staff roles" not in source
    assert "StaffRolesModal" not in source



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
    assert "ingredient_usage_embed(include_usable_item_recipes(get_guild_recipe_data(interaction.guild_id)), ingredient)" in source



def test_slash_command_recipe_tools_include_usable_item_recipes():
    source = Path("bot.py").read_text(encoding="utf-8")
    for call in (
        "search_embed(include_usable_item_recipes(",
        "calculate_recipe_ingredients(include_usable_item_recipes(",
        "inventory_plan(include_usable_item_recipes(",
        "dependency_chain(include_usable_item_recipes(",
        "expanded_production_requirements(",
        "multi_recipe_plan(include_usable_item_recipes(",
        "advanced_search(include_usable_item_recipes(",
        "recipe_comparison(include_usable_item_recipes(",
    ):
        assert call in source


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



def test_extended_player_and_server_tools_are_wired():
    source = Path("bot.py").read_text(encoding="utf-8")
    for feature in (
        "class RestoreInventoryModal",
        "class ShareShoppingListView",
        "class AliasManagerModal",
        "class ProfileCreateModal",
        "class ProfileSelectModal",
        "System health check",
        "Activity audit log",
        "Manage ingredient aliases",
        "Create server recipe profile",
        "Switch server recipe profile",
        "what can i craft",
        "Export backup",
        "Restore backup",
    ):
        assert feature in source


def test_runtime_files_for_new_features_are_ignored():
    ignore = Path(".gitignore").read_text(encoding="utf-8")
    for filename in ("aliases.json", "audit-log.json", "guild-profiles.json", "profiles/"):
        assert filename in ignore


def test_server_profile_and_audit_data_are_guild_scoped():
    source = Path("bot.py").read_text(encoding="utf-8")
    assert "def get_guild_recipe_data(guild_id)" in source
    assert "def save_guild_recipe_data(guild_id, data)" in source
    assert '"guild_id": guild_id' in source
    assert 'item.get("guild_id") == interaction.guild_id' in source


def test_related_table_search_finds_weed_synonyms_across_recipes():
    from enhancements import related_table_search

    data = {"tables": [
        {"name": "Hash Table", "recipes": [
            {"name": "Hashish", "ingredients": [["Clean Weed Bud", 5], ["Distilled Water", 2]]},
        ]},
        {"name": "Grinding Station", "recipes": [
            {"name": "Kief", "ingredients": [["Clean Weed Bud", 4]]},
        ]},
        {"name": "Unrelated Table", "recipes": [
            {"name": "Sandwich", "ingredients": [["Bread", 1]]},
        ]},
    ]}
    results = related_table_search(data, "What tables have anything to do with weed or marijuana or bud?")
    assert {item["table"] for item in results} == {"Hash Table", "Grinding Station"}
    by_table = {item["table"]: item for item in results}
    assert "Hashish" in [recipe["recipe"] for recipe in by_table["Hash Table"]["recipes"]]
    assert "Kief" in [recipe["recipe"] for recipe in by_table["Grinding Station"]["recipes"]]


def test_related_table_search_does_not_invent_tables_or_recipes():
    from enhancements import related_table_search

    data = {"tables": [{"name": "Plain Table", "recipes": [{"name": "Sandwich", "ingredients": [["Bread", 1]]}]}]}
    assert related_table_search(data, "weed marijuana bud") == []


def test_chat_message_handler_exposes_related_table_search():
    source = Path("bot.py").read_text(encoding="utf-8")
    assert "related_table_search" in source
    assert "Related crafting tables:" in source




def test_hand_tablet_press_usable_directory_lists_all_pill_recipes_and_exact_ingredients():
    source = Path("bot.py").read_text(encoding="utf-8")
    expected = (
        "Hand Tablet Press — Pill Recipes (1/2)",
        "Hand Tablet Press — Pill Recipes (2/2)",
        "Xanax** — 1x Alprazolam Powder + 1x Pill Binder",
        "Valium** — 1x Diazepam Powder + 1x Pill Binder",
        "Adderall** — 1x Amphetamine Powder + 1x Pill Binder",
        "Quaaludes** — 1x Methaqualone Powder + 1x Pill Binder",
        "Tramadol** — 1x Tramadol HCl + 1x Pill Binder",
        "Ritalin** — 1x Methylphenidate Powder + 1x Pill Binder",
        "Captagon** — 1x Fenethylline Powder + 1x Pill Binder",
        "Modafinil** — 1x Modafinil Powder + 1x Pill Binder",
        "DOM** — 1x DOM Powder + 1x Pill Binder",
        "Dilaudid** — 1x Hydromorphone HCl + 1x Pill Binder",
        "Opana** — 1x Oxymorphone HCl + 1x Pill Binder",
        "Klonopin** — 1x Clonazepam Powder + 1x Pill Binder",
        "Ambien** — 1x Zolpidem Powder + 1x Pill Binder",
        "Soma** — 1x Carisoprodol Powder + 1x Pill Binder",
        "6-APB** — 1x 6-APB Succinate + 1x Pill Binder",
        "BZP** — 1x BZP HCl + 1x Pill Binder",
        "Ecstasy pill** — 1x Ecstasy crystals + 1x Pill Binder",
        "Hydrocodone** — 1x Hydrocodone Bitartrate + 2x Acetaminophen + 1x Pill Binder",
    )
    for entry in expected:
        assert entry in source, entry


def test_weed_growing_calculator_returns_both_systems_and_correct_shop_costs():
    from enhancements import calculate_weed_growing_requirements

    result = calculate_weed_growing_requirements("How much to grow 100 weed plants?")
    assert result["plants"] == 100
    assert result["systems"]["smoke"]["items"]["Spring Water"] == 100
    assert result["systems"]["smoke"]["items"]["Flower Pot"] == 100
    assert result["systems"]["smoke"]["items"]["Trowel"] == 1
    assert result["systems"]["smoke"]["total"] == 37615
    assert result["systems"]["grape"]["items"]["Bloom Booster"] == 100
    assert result["systems"]["grape"]["items"]["Watering Can"] == 100
    assert result["systems"]["grape"]["total"] == 42100


def test_weed_growing_calculator_applies_different_grass_rules_to_each_system():
    from enhancements import calculate_weed_growing_requirements

    result = calculate_weed_growing_requirements("How much to grow 100 weed plants in grass?")
    assert result["systems"]["smoke"]["items"]["Flower Pot"] == 100
    assert result["systems"]["smoke"]["total"] == 37615
    assert "Flower Pot" not in result["systems"]["grape"]["items"]
    assert result["systems"]["grape"]["items"]["Watering Can"] == 100
    assert result["systems"]["grape"]["total"] == 17100



def test_bot_has_no_internal_role_or_guild_permission_gates():
    source = Path("bot.py").read_text(encoding="utf-8")
    for removed in ("access_roles_for_guild", "can_manage_crafting", "is_guild_admin",
                    "PERMISSIONS_FILE", "StaffRolesModal", "Configure staff roles",
                    "Manage Server permission", "approved crafting staff role",
                    "guild_permissions", "role_ids"):
        assert removed not in source
    assert 'name="setrole"' not in source
    assert 'name="removerole"' not in source
    assert "Admin tools" in source
    assert 'value="admin"' in source


def test_prefix_lookups_are_not_mistaken_for_discord_integration_commands():
    source = Path("bot.py").read_text(encoding="utf-8")
    assert "Prefix lookups are message-based" in source
    assert "if message.guild is None:" in source
    assert "access_roles_for_guild" not in source


def test_pharmacy_postal_9072_items_are_in_shop_directory_and_price_lookup():
    source = Path("bot.py").read_text(encoding="utf-8")
    assert "Pharmacy — Postal 9072" in source
    assert "Medical & Wellness (9 items)" in source
    assert "Party & Gender Reveal (5 items)" in source

    from enhancements import calculate_shop_price_query

    expected = {
        "bandage": 150,
        "feminine pad": 10,
        "chill pills": 100,
        "electrolyte drink": 20,
        "cough syrup": 50,
        "condoms": 10,
        "pregnancy test box": 200,
        "prenatal vitamins": 100,
        "baby oil": 50,
        "confetti cannon": 50,
        "confetti popper": 50,
        "gender reveal balloon": 50,
        "gender reveal gift box": 50,
        "gender reveal smoke": 50,
    }
    for item, price in expected.items():
        result = calculate_shop_price_query(f"how much is {item}?")
        assert result["unit_price"] == price, item
        assert result["shop"] == "Pharmacy — Postal 9072", item

    # This similarly named product is sold by the Blackmarket Doctor, not the Pharmacy.
    dextromethorphan = calculate_shop_price_query("how much is dextromethorphan cough syrup?")
    assert dextromethorphan["unit_price"] == 60
    assert dextromethorphan["shop"] == "Blackmarket Doctor — Postal 3009"


def test_weed_growing_calculator_defaults_to_one_plant_when_quantity_is_omitted():
    from enhancements import calculate_weed_growing_requirements

    result = calculate_weed_growing_requirements(
        "What do I need to grow weed and how much will I spend?"
    )
    assert result["plants"] == 1
    assert result["systems"]["smoke"]["total"] == 490
    assert result["systems"]["grape"]["total"] == 520
    assert result["systems"]["smoke"]["items"]["Weed Seed"] == 1
    assert result["systems"]["grape"]["items"]["Bloom Booster"] == 1



def test_system_two_watering_can_is_not_reusable():
    from enhancements import calculate_weed_growing_requirements

    result = calculate_weed_growing_requirements("How much for 500 weed plants System 2?")
    assert result["systems"]["grape"]["items"]["Watering Can"] == 500
    assert result["systems"]["grape"]["costs"]["Watering Can"] == 7500
    assert result["systems"]["grape"]["total"] == 210100
    assert "one Watering Can per plant" in result["systems"]["grape"]["note"]




def test_generic_question_handler_keeps_bang_prefix_and_searches_all_saved_information():
    source = Path("bot.py").read_text(encoding="utf-8")
    assert 'if not content.startswith("!"):' in source
    assert "postal_match = re.search" in source
    assert "query_data = include_usable_item_recipes(data)" in source
    assert "ingredient_usage_embed(query_data, ingredient_query)" in source
    assert "saved_information_matches(query)" in source
    assert "calculate_inventory_limited_batches(query_data" in source
    assert "Recipes covered by your listed stock (recorded ingredients):" in source
    assert "def include_usable_item_recipes(" in source
    assert "attach_location_recipe_warnings(" in source
    assert "match.get(\"notes\")" in source
    assert "def saved_information_matches(" in source


def test_no_item_specific_meth_calculator_is_hard_coded():
    source = Path("bot.py").read_text(encoding="utf-8") + Path("enhancements.py").read_text(encoding="utf-8")
    assert "calculate_meth_requirements" not in source
    assert "pseudoephedrine // 4" not in source


def test_chemical_supplier_price_lookup_covers_saved_items():
    from enhancements import calculate_shop_price_query

    expected = {
        "Sodium Hydroxide (Lye)": 80,
        "Citric Acid": 20,
        "Sulfuric Acid": 50,
        "Slaked Lime": 15,
        "Succinic Acid": 40,
        "Acetone": 60,
        "Isopropyl Alcohol": 50,
        "Distilled Water": 20,
        "Naphtha": 70,
        "Grain Alcohol": 45,
        "Butane Canister": 30,
        "Sodium Benzoate": 150,
        "Ammonia": 175,
        "Hydrogen Peroxide": 40,
        "Urea": 25,
        "Formaldehyde": 60,
        "Potassium Permanganate": 60,
        "Sodium Acetate": 40,
        "Filter Paper": 10,
    }
    for item, price in expected.items():
        result = calculate_shop_price_query(f"where can I buy {item}?")
        assert result["unit_price"] == price, item
        assert result["shop"] == "Chemical Supplier — Postal 10105", item




def test_usable_item_recipe_parser_keeps_tools_and_combines_hand_tablet_press_pages():
    from enhancements import parse_usable_item_sections

    tables = parse_usable_item_sections([
        (
            "🧴 2L Water Bottle",
            "• **Meth** — 4x Pseudoephedrine + 1x Ammonia + 1x 2L Water Bottle\n"
            "  **Tool (not consumed):** 1x Gas Mask",
        ),
        (
            "💊 Hand Tablet Press — Pill Recipes (1/2)",
            "• **Xanax** — 1x Alprazolam Powder + 1x Pill Binder",
        ),
        (
            "💊 Hand Tablet Press — Pill Recipes (2/2)",
            "• **Hydrocodone** — 1x Hydrocodone Bitartrate + 2x Acetaminophen + 1x Pill Binder",
        ),
    ])
    by_name = {table["name"]: table for table in tables}
    bottle = by_name["Usable Item — 2L Water Bottle"]["recipes"][0]
    assert bottle["name"] == "Meth"
    assert bottle["tools"] == ["Gas Mask"]
    press = by_name["Usable Item — Hand Tablet Press"]["recipes"]
    assert [recipe["name"] for recipe in press] == ["Xanax", "Hydrocodone"]
    assert press[0]["ingredients"] == [["Alprazolam Powder", 1], ["Pill Binder", 1]]


def test_saved_information_lookup_is_connected_to_shop_location_usable_and_help_pages():
    source = Path("bot.py").read_text(encoding="utf-8")
    start = source.index("def saved_information_matches(")
    end = source.index("def commands_embed(", start)
    helper = source[start:end]
    for page in ("shops_embed()", "locations_embed()", "usable_embed()", "commands_embed()"):
        assert page in helper


def test_location_directory_documents_unresolved_10060_hidden_materials():
    source = Path("bot.py").read_text(encoding="utf-8")
    assert "1 hidden material" in source
    assert "exact item name is not recorded" in source





def test_reflux_rig_has_all_14_exact_user_supplied_recipes():
    data = json.loads(Path("recipes.json").read_text(encoding="utf-8"))
    table = next(table for table in data["tables"] if table["name"] == "Reflux Rig")
    recipes = {recipe["name"]: recipe["ingredients"] for recipe in table["recipes"]}
    assert len(recipes) == 14
    for number in range(1, 10):
        assert recipes[f"Item Type {number}"] == [
            [f"Crude Substance {number}", 1], ["Solvent A", 1], ["Filter Medium", 1]
        ]
    for number in range(10, 13):
        assert recipes[f"Item Type {number}"] == [
            [f"Crude Substance {number}", 1], ["Solvent B", 1], ["Filter Medium", 1]
        ]
    assert recipes["Item Type 13"] == [
        ["Crude Substance 13", 1], ["Reagent C", 1], ["Filter Medium", 1]
    ]
    assert recipes["Item Type 14"] == [
        ["Precursor D", 1], ["Reagent E", 1], ["Solvent B", 1]
    ]


def test_reflux_rig_recipes_are_available_to_shared_search_and_calculators():
    from enhancements import calculate_recipe_ingredients, chat_recipe_search

    data = json.loads(Path("recipes.json").read_text(encoding="utf-8"))
    matches = chat_recipe_search(data, "How do I make Item Type 14 on the Reflux Rig?")
    assert any(match["recipe"] == "Item Type 14" for match in matches)
    result = calculate_recipe_ingredients(data, "Reflux Rig", "Item Type 14", 5)
    assert result["ingredients"] == {
        "Precursor D": 5, "Reagent E": 5, "Solvent B": 5
    }


def test_system_one_requires_flower_pot_even_when_planted_in_grass():
    from enhancements import calculate_weed_growing_requirements

    result = calculate_weed_growing_requirements("How much for 10 weed plants in grass?")
    assert result["systems"]["smoke"]["items"]["Flower Pot"] == 10
    assert result["systems"]["smoke"]["total"] == 4015
    assert "Flower Pot" not in result["systems"]["grape"]["items"]
    assert result["systems"]["grape"]["total"] == 1685
