import pytest

from crafting import CraftingDirectoryView, load_recipe_data, recipe_embed, search_embed


def test_glovebox_table_loads_from_json():
    data = load_recipe_data()
    table = next(table for table in data["tables"] if table["name"] == "Glovebox Table")
    assert len(table["recipes"]) == 11


def test_recipe_embed_separates_consumables_and_tools():
    data = load_recipe_data()
    table = data["tables"][0]
    recipe = next(item for item in table["recipes"] if item["name"] == "Fentanyl bag")
    embed = recipe_embed(table["name"], recipe)
    fields = {field.name: field.value for field in embed.fields}
    assert "Required ingredients" in fields
    assert "Tools (not consumed)" in fields
    assert "Plastic bag" in fields["Required ingredients"]
    assert "Scale" in fields["Tools (not consumed)"]


def test_search_matches_recipe_ingredients():
    data = load_recipe_data()
    embed = search_embed(data, "Mannitol")
    assert embed.fields
    assert any("Tranq" in field.name or "Carfentanil" in field.name for field in embed.fields)


@pytest.mark.asyncio
async def test_private_menu_view_builds_dropdown_controls():
    data = load_recipe_data()
    view = CraftingDirectoryView(123456789, data)
    assert len(view.children) == 4
    assert view.children[0].placeholder == "Choose a crafting table"
    assert view.children[1].placeholder == "Choose a recipe"
    view.stop()
