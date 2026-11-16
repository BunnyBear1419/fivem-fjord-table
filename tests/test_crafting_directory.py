from pathlib import Path

import pytest

from crafting import (
    CraftingDirectoryView, find_matches, load_recipe_data, parse_ingredients,
    recipe_embed, search_embed, build_ingredient_directory, ingredient_directory_document, ingredient_directory_embed,
)


def test_glovebox_table_loads_from_json():
    data = load_recipe_data()
    table = next(table for table in data["tables"] if table["name"] == "Glovebox Table")
    assert len(table["recipes"]) == 11


def test_recipe_embed_separates_consumables_and_tools():
    data = load_recipe_data()
    table = next(table for table in data["tables"] if table["name"] == "Glovebox Table")
    recipe = next(item for item in table["recipes"] if item["name"] == "Fentanyl bag")
    embed = recipe_embed(table["name"], recipe)
    fields = {field.name: field.value for field in embed.fields}
    assert "Required ingredients" in fields
    assert "Tools (not consumed)" in fields
    assert "Plastic bag" in fields["Required ingredients"]
    assert "Scale" in fields["Tools (not consumed)"]


def test_search_finds_ingredients_and_respects_table_filter():
    data = load_recipe_data()
    matches = find_matches(data, "Mannitol")
    assert matches
    assert any("Tranq" in recipe["name"] or "Carfentanil" in recipe["name"] for _, recipe in matches)
    filtered = find_matches(data, "Mannitol", "Glovebox")
    assert filtered
    assert all(table == "Glovebox Table" for table, _ in filtered)


def test_search_embed_shows_count_and_results():
    data = load_recipe_data()
    embed = search_embed(data, "Mannitol")
    assert "matching recipe" in embed.description
    assert embed.fields


def test_ingredient_parser_preserves_duplicate_ingredients():
    assert parse_ingredients("Plastic bag x2, Powder x1, Plastic bag x3") == [
        ["Plastic bag", 2], ["Powder", 1], ["Plastic bag", 3]
    ]


def test_ingredient_parser_rejects_zero_quantity():
    with pytest.raises(ValueError):
        parse_ingredients("Plastic bag x0")


@pytest.mark.asyncio
async def test_private_menu_view_builds_dropdown_controls():
    data = load_recipe_data()
    view = CraftingDirectoryView(123456789, data)
    assert len(view.children) == 8
    assert view.children[4].label == '◀ Tables'
    assert view.children[5].label == 'More tables ▶'
    assert view.children[6].label == 'Home'
    assert view.children[7].label == 'Refresh'
    assert view.children[0].placeholder == "Choose a crafting table"
    assert view.children[1].placeholder == "Choose a recipe"
    view.stop()



def test_all_ingredient_directory_groups_exact_names_and_preserves_occurrences():
    data = {"tables": [{"name": "Test Table", "recipes": [
        {"name": "Test Recipe", "ingredients": [["Coca Leaf", 1], ["Coca Leaves", 2], ["Coca Leaf", 3]]}
    ]}]}
    directory = build_ingredient_directory(data)
    by_name = {item["ingredient"]: item["uses"] for item in directory}
    assert set(by_name) == {"Coca Leaf", "Coca Leaves"}
    assert [use["quantity"] for use in by_name["Coca Leaf"]] == [1, 3]
    document = ingredient_directory_document(data)
    assert "Coca Leaf\n" in document
    assert "Coca Leaves\n" in document
    assert document.count("requires ×") == 3
    embed = ingredient_directory_embed(data)
    assert embed.fields



def test_ingredient_lookup_includes_non_consumed_tool_requirements():
    from crafting import find_tool_usage, ingredient_usage_embed

    data = {"tables": [{"name": "Bench", "recipes": [
        {"name": "Widget", "ingredients": [["Wire", 2]], "tools": ["Press"]},
        {"name": "Other Widget", "ingredients": [["Bolt", 1]], "tools": ["Press"]},
    ]}]}
    matches = find_tool_usage(data, "press")
    assert matches == [{
        "table": "Bench",
        "recipes": [
            {"recipe": "Widget", "tool": "press", "occurrences": 1, "notes": []},
            {"recipe": "Other Widget", "tool": "press", "occurrences": 1, "notes": []},
        ],
    }]
    embed = ingredient_usage_embed(data, "Press")
    assert any(field.name == "Required as a tool: Bench" for field in embed.fields)
    assert "not consumed" in next(field.value for field in embed.fields if field.name == "Required as a tool: Bench")



def test_recipe_search_and_recipe_embed_surface_location_data_warnings():
    from crafting import recipe_embed, search_embed

    data = {"tables": [{"name": "Bench", "recipes": [{
        "name": "Heist Drill",
        "ingredients": [["drill_bit", 2]],
        "tools": [],
        "notes": ["Postal 10060 notes list an unnamed hidden material."],
    }]}]}
    embed = recipe_embed("Bench", data["tables"][0]["recipes"][0])
    assert any(field.name == "Data review notes" for field in embed.fields)
    search = search_embed(data, "Heist Drill")
    assert "Postal 10060 notes list an unnamed hidden material." in search.fields[0].value


def test_crafting_directory_has_refresh_callback_and_preserves_current_table():
    source = Path("crafting.py").read_text(encoding="utf-8")
    assert "refresh.callback = self._refresh" in source
    assert "latest = self.refresh_data()" in source
    assert "self.table_index = min(self.table_index, max(0, len(self.tables) - 1))" in source



def test_recipe_backup_verifier_accepts_valid_backup_and_rejects_corrupt_json(tmp_path):
    import json
    from crafting import verify_recipe_backup

    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps({"tables": [{"name": "Bench", "recipes": [{"name": "Widget", "ingredients": [["Wire", 2]], "tools": []}]}]}), encoding="utf-8")
    result = verify_recipe_backup(valid)
    assert result["valid"] is True
    assert result["tables"] == 1
    assert result["recipes"] == 1

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    failed = verify_recipe_backup(corrupt)
    assert failed["valid"] is False
    assert failed["errors"]
