from enhancements import (
    calculate_recipe_ingredients, recipes_csv_bytes, recipes_xlsx_bytes,
    table_ingredient_sets, validate_recipe_data,
)


def test_shopping_list_multiplies_batches_and_sums_duplicate_rows():
    data = {"tables": [{"name": "Bench", "recipes": [
        {"name": "Widget", "ingredients": [["Wire", 2], ["Wire", 3], ["Bolt", 1]], "tools": ["Wrench"]}
    ]}]}
    result = calculate_recipe_ingredients(data, "bench", "widget", 4)
    assert result["ingredients"] == {"Wire": 20, "Bolt": 4}
    assert result["tools"] == ["Wrench"]
    assert data["tables"][0]["recipes"][0]["ingredients"] == [["Wire", 2], ["Wire", 3], ["Bolt", 1]]


def test_shopping_list_rejects_invalid_batch_counts_and_missing_recipes():
    data = {"tables": [{"name": "Bench", "recipes": []}]}
    import pytest
    with pytest.raises(ValueError):
        calculate_recipe_ingredients(data, "Bench", "Widget", 0)
    with pytest.raises(ValueError):
        calculate_recipe_ingredients(data, "Bench", "Widget", 1)


def test_table_comparison_uses_distinct_words_and_shared_ingredients():
    data = {"tables": [
        {"name": "A", "recipes": [{"name": "one", "ingredients": [["Coca Leaf", 1], ["Shared", 2]]}]},
        {"name": "B", "recipes": [{"name": "two", "ingredients": [["Coca Leaves", 1], ["Shared", 1]]}]},
    ]}
    tables, _ = table_ingredient_sets(data)
    assert "coca leaf" in tables["A"]
    assert "coca leaves" in tables["B"]
    assert "shared" in tables["A"] & tables["B"]


def test_validation_reports_bad_quantities_and_does_not_merge_spelling():
    data = {"tables": [{"name": "Bench", "recipes": [
        {"name": "one", "ingredients": [["Wire", 0], ["Wrie", 1]]}
    ]}]}
    findings = validate_recipe_data(data)
    assert any(item["severity"] == "error" and "invalid quantity" in item["message"] for item in findings)
    assert any("Possible spelling variation" in item["message"] for item in findings)


def test_csv_and_excel_exports_keep_duplicate_ingredient_occurrences():
    data = {"tables": [{"name": "Bench", "recipes": [
        {"name": "Widget", "ingredients": [["Wire", 2], ["Wire", 3]]}
    ]}]}
    csv_data = recipes_csv_bytes(data).decode("utf-8-sig")
    assert csv_data.count("Wire") == 2
    excel_data = recipes_xlsx_bytes(data)
    assert excel_data[:2] == b"PK"


def test_dependency_chain_traces_nested_outputs_and_stops_cycles():
    from enhancements import dependency_chain, dependency_lines
    data = {"tables": [{"name": "Bench", "recipes": [
        {"name": "Final Item", "ingredients": [["Intermediate", 2]]},
        {"name": "Intermediate", "ingredients": [["Base", 3]]},
        {"name": "Base", "ingredients": [["Final Item", 1]]},
    ]}]}
    chain = dependency_chain(data, "Final Item")
    lines = dependency_lines(chain)
    assert any("Intermediate" in line for line in lines)
    assert any("cycle stopped" in line for line in lines)


def test_inventory_calculator_combines_duplicate_stock_and_finds_missing():
    from enhancements import inventory_plan
    data = {"tables": [{"name": "Bench", "recipes": [
        {"name": "Widget", "ingredients": [["Wire", 2], ["Wire", 1], ["Bolt", 2]]}
    ]}]}
    result = inventory_plan(data, "Bench", "Widget", 3, "Wire x5, Wire x1, Bolt x2")
    assert result["available_batches"] == 1
    assert result["missing"] == {"Wire": 3, "Bolt": 4}


def test_multi_recipe_planner_combines_totals_across_recipes():
    from enhancements import multi_recipe_plan
    data = {"tables": [{"name": "Bench", "recipes": [
        {"name": "A", "ingredients": [["Wire", 2]]},
        {"name": "B", "ingredients": [["Wire", 3], ["Bolt", 1]]},
    ]}]}
    result = multi_recipe_plan(data, [("Bench", "A", 2), ("Bench", "B", 3)])
    assert result["ingredients"] == {"Wire": 13, "Bolt": 3}


def test_advanced_search_filters_table_ingredient_tool_and_minimum():
    from enhancements import advanced_search
    data = {"tables": [{"name": "Bench", "recipes": [
        {"name": "Widget", "ingredients": [["Wire", 2], ["Bolt", 1]], "tools": ["Hammer"]},
        {"name": "Other", "ingredients": [["Wire", 1]], "tools": ["Saw"]},
    ]}]}
    results = advanced_search(data, table_filter="Bench", ingredient_filter="wire", tool_filter="hammer", min_ingredients=2)
    assert [recipe["name"] for _, recipe in results] == ["Widget"]


def test_recipe_comparison_reports_shared_and_exclusive_items():
    from enhancements import recipe_comparison
    data = {"tables": [{"name": "Bench", "recipes": [
        {"name": "A", "ingredients": [["Wire", 2], ["Bolt", 1]]},
        {"name": "B", "ingredients": [["Wire", 1], ["Nail", 3]]},
    ]}]}
    result = recipe_comparison(data, "Bench", "A", "Bench", "B")
    assert result["shared"] == ["Wire"]
    assert result["only_a"] == ["Bolt"]
    assert result["only_b"] == ["Nail"]


def test_import_merge_skips_conflicts_and_preserves_duplicate_ingredient_rows():
    from enhancements import merge_recipe_import
    current = {"tables": [{"name": "Bench", "recipes": [
        {"name": "Existing", "ingredients": [["Wire", 1]]}
    ]}]}
    incoming = {"tables": [{"name": "Bench", "recipes": [
        {"name": "Existing", "ingredients": [["Bolt", 1]]},
        {"name": "New", "ingredients": [["Wire", 2], ["Wire", 3]]},
    ]}]}
    merged, summary = merge_recipe_import(current, incoming, "skip")
    assert summary["skipped"] == 1
    assert summary["recipes_added"] == 1
    new_recipe = next(r for r in merged["tables"][0]["recipes"] if r["name"] == "New")
    assert new_recipe["ingredients"] == [["Wire", 2], ["Wire", 3]]


def test_stable_ids_are_added_and_preserved_when_names_change():
    from enhancements import ensure_stable_ids
    data = {"tables": [{"name": "Bench", "recipes": [{"name": "Widget", "ingredients": []}]}]}
    ensure_stable_ids(data)
    table_id = data["tables"][0]["id"]
    recipe_id = data["tables"][0]["recipes"][0]["id"]
    data["tables"][0]["name"] = "Renamed Bench"
    data["tables"][0]["recipes"][0]["name"] = "Renamed Widget"
    ensure_stable_ids(data)
    assert data["tables"][0]["id"] == table_id
    assert data["tables"][0]["recipes"][0]["id"] == recipe_id


def test_new_features_are_exposed_in_private_menu_and_admin_tools():
    source = open("bot.py", encoding="utf-8").read()
    for feature in ("Production chains", "Inventory calculator", "Multi-recipe planner", "Advanced search", "Item database", "Recipe comparison"):
        assert feature in source
    for feature in ("Import / merge recipe JSON", "Configure staff roles", "View crafting analytics"):
        assert feature in source


def test_import_rejects_malformed_rows_and_keeps_valid_duplicate_occurrences():
    import pytest
    from enhancements import merge_recipe_import
    current = {"tables": [{"name": "Bench", "recipes": []}]}
    incoming = {"tables": [{"name": "Bench", "recipes": [
        {"name": "Valid", "ingredients": [["Wire", 1], ["Wire", 1]]}
    ]}]}
    merged, summary = merge_recipe_import(current, incoming, "skip")
    assert summary["recipes_added"] == 1
    assert merged["tables"][0]["recipes"][0]["ingredients"] == [["Wire", 1], ["Wire", 1]]
    bad = {"tables": [{"name": "Bench", "recipes": [
        {"name": "Broken", "ingredients": [["Wire", True]]}
    ]}]}
    with pytest.raises(ValueError):
        merge_recipe_import(current, bad, "skip")


def test_import_rejects_unknown_conflict_modes():
    import pytest
    from enhancements import merge_recipe_import
    data = {"tables": [{"name": "Bench", "recipes": []}]}
    with pytest.raises(ValueError):
        merge_recipe_import(data, data, "merge-everything")


def test_recipe_validator_handles_malformed_table_and_recipe_shapes():
    from enhancements import validate_recipe_data
    findings = validate_recipe_data({"tables": [None, {"name": "Bench", "recipes": [None]}]})
    assert any("not an object" in item["message"] for item in findings)


def test_actual_repository_recipe_data_has_no_structural_errors():
    import json
    from pathlib import Path
    from enhancements import validate_recipe_data
    data = json.loads(Path("recipes.json").read_text(encoding="utf-8"))
    findings = validate_recipe_data(data)
    assert not [item for item in findings if item["severity"] == "error"]


def test_storage_writes_atomically_and_preserves_corrupt_files_for_recovery(tmp_path):
    import pytest
    from storage import atomic_write_json, read_json
    path = tmp_path / "sample.json"
    atomic_write_json(path, {"tables": [{"name": "Bench"}]})
    assert read_json(path, {}) == {"tables": [{"name": "Bench"}]}
    path.write_text("{broken json", encoding="utf-8")
    with pytest.raises(ValueError, match="original file was preserved"):
        read_json(path, {})
    assert path.read_text(encoding="utf-8") == "{broken json"


def test_brewing_kettle_table_is_bundled_with_all_user_supplied_recipes():
    import json
    from pathlib import Path
    data = json.loads(Path("recipes.json").read_text(encoding="utf-8"))
    table = next(item for item in data["tables"] if item["name"] == "Brewing Kettle")
    assert table["id"] == "table_010"
    assert len(table["recipes"]) == 15
    assert table["recipes"][0]["name"] == "Ayahuasca Brew"
    assert table["recipes"][0]["ingredients"] == [
        ["Shredded Caapi Vine", 2],
        ["Chacruna Leaves", 2],
        ["Distilled Water", 2],
        ["Cheesecloth", 1],
    ]
    assert table["recipes"][-1]["name"] == "San Pedro Brew"
    assert table["recipes"][-1]["ingredients"] == [
        ["Dried San Pedro", 2],
        ["Distilled Water", 1],
    ]
    assert all(recipe["id"].startswith("recipe_010_") for recipe in table["recipes"])


def test_herb_drying_rack_table_contains_all_user_supplied_recipes():
    import json
    from pathlib import Path
    data = json.loads(Path("recipes.json").read_text(encoding="utf-8"))
    table = next(item for item in data["tables"] if item["name"] == "Herb Drying Rack")
    assert table["id"] == "table_011"
    assert len(table["recipes"]) == 11
    assert table["recipes"][0]["name"] == "Peyote"
    assert table["recipes"][0]["ingredients"] == [["Fresh Peyote Buttons", 3]]
    assert table["recipes"][9]["name"] == "Spice (K2)"
    assert table["recipes"][9]["ingredients"] == [["Spice Spray", 1], ["Damiana Leaves", 2]]
    assert table["recipes"][-1]["name"] == "Dried San Pedro"
    assert table["recipes"][-1]["ingredients"] == [["San Pedro Cactus", 2]]
    assert all(recipe["id"].startswith("recipe_011_") for recipe in table["recipes"])
