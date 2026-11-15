from enhancements import calculate_shop_price_query


def test_bulk_45_ammo_price_question():
    result = calculate_shop_price_query("if I want 2000 45 ammo how much will I spend?")
    assert result == {
        "quantity": 2000,
        "item": "SMG Ammo (.45 ACP)",
        "shop": "Weapon & Ammo Store",
        "unit_price": 23,
        "total": 46000,
    }


def test_hotdogs_price_question_accepts_plural_and_compact_spelling():
    result = calculate_shop_price_query("If I want 500 hotdogs how much would that cost?")
    assert result["item"] == "Hot Dog"
    assert result["quantity"] == 500
    assert result["unit_price"] == 2
    assert result["total"] == 1000


def test_price_calculator_ignores_non_price_recipe_searches():
    assert calculate_shop_price_query("how do I make meth?") is None


def test_price_calculator_explains_unknown_shop_item():
    result = calculate_shop_price_query("how much would 50 mystery widgets cost?")
    assert "error" in result
