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


def test_distilled_water_where_to_buy_and_unit_price_without_quantity():
    result = calculate_shop_price_query("where do I buy Distilled Water & for how much?")
    assert result == {
        "quantity": None,
        "item": "Distilled Water",
        "shop": "Chemical Supplier — Postal 10105",
        "unit_price": 20,
        "total": None,
    }


def test_distilled_water_price_question_without_quantity():
    result = calculate_shop_price_query("how much does distilled water cost?")
    assert result["item"] == "Distilled Water"
    assert result["unit_price"] == 20
    assert result["quantity"] is None
    assert result["total"] is None



def test_equipment_dealer_prices_are_searchable_from_the_saved_locations_directory():
    expected = {
        "Meth Table": 5000,
        "Weed Table": 4000,
        "Coke Table": 5000,
        "Chemistry Table": 6500,
        "Pill Press": 7500,
        "Reflux Rig": 9000,
        "Extraction Bench": 8000,
        "Glovebox": 15000,
        "Brewing Kettle": 2500,
        "Lab Freezer": 4000,
        "Herb Drying Rack": 2000,
        "Grinding Station": 3000,
        "Capsule Filler": 3500,
        "Burner Phone": 500,
        "Tablet Die Set": 1200,
        "Hand Tablet Press": 900,
    }
    for item, price in expected.items():
        result = calculate_shop_price_query(f"how much is {item}?")
        assert result["item"] == item
        assert result["unit_price"] == price
        assert result["shop"] == "Equipment Dealer — Postals 9275–9277"
