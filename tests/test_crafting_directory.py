import pytest

from crafting import (
    CraftingDirectoryView, find_matches, load_recipe_data, parse_ingredients,
    recipe_embed, search_embed,
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
    assert len(view.children) == 4
    assert view.children[0].placeholder == "Choose a crafting table"
    assert view.children[1].placeholder == "Choose a recipe"
    view.stop()
