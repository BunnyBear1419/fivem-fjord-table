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
