"""Low-memory reporting, export, validation and comparison helpers for the crafting bot."""
import csv
import io
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from typing import Any

import discord


def calculate_recipe_ingredients(data: dict[str, Any], table_name: str, recipe_name: str, batches: int = 1):
    """Calculate a shopping list, summing repeated ingredient rows without altering source data."""
    if not isinstance(batches, int) or batches < 1 or batches > 999:
        raise ValueError("Batch count must be between 1 and 999.")
    table = next((t for t in data.get("tables", []) if t.get("name", "").casefold().strip() == table_name.casefold().strip()), None)
    if table is None:
        raise ValueError(f"Crafting table not found: {table_name}")
    recipe = next((r for r in table.get("recipes", []) if r.get("name", "").casefold().strip() == recipe_name.casefold().strip()), None)
    if recipe is None:
        raise ValueError(f"Recipe not found in {table_name}: {recipe_name}")
    totals = {}
    for name, quantity in recipe.get("ingredients") or []:
        totals[name] = totals.get(name, 0) + int(quantity) * batches
    return {"table": table["name"], "recipe": recipe["name"], "batches": batches, "ingredients": totals, "tools": recipe.get("tools") or []}


def recipe_shopping_embed(result: dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(
        title=f"🧮 Shopping list: {result['recipe']}",
        description=f"**Table:** {result['table']}\n**Batches:** {result['batches']}\nRepeated ingredient rows are added together for the total.",
        color=discord.Color.from_rgb(57, 75, 111),
    )
    lines = [f"• **{name}** ×{quantity}" for name, quantity in result["ingredients"].items()]
    text = "\n".join(lines) or "No ingredients recorded."
    if len(text) > 3900:
        text = text[:3850] + "\n… list truncated; use the exports for the complete data."
    embed.add_field(name="Total ingredients required", value=text, inline=False)
    if result["tools"]:
        embed.add_field(name="Tools (not consumed)", value=", ".join(result["tools"])[:1024], inline=False)
    return embed


def table_ingredient_sets(data: dict[str, Any]):
    tables = {}
    display_names = {}
    for table in data.get("tables", []):
        names = set()
        for recipe in table.get("recipes", []):
            for ingredient, _quantity in recipe.get("ingredients") or []:
                key = str(ingredient).casefold().strip()
                if key:
                    names.add(key)
                    display_names.setdefault(key, str(ingredient).strip())
        tables[table.get("name", "Unnamed table")] = names
    return tables, display_names


def table_comparison_embed(data: dict[str, Any]) -> discord.Embed:
    tables, display_names = table_ingredient_sets(data)
    counts = Counter(key for names in tables.values() for key in names)
    shared = sorted((display_names[k] for k, count in counts.items() if count > 1), key=str.casefold)
    embed = discord.Embed(
        title="⚖️ Crafting Table Comparison",
        description=f"**{len(tables)} tables** · **{len(counts)} distinct ingredient names** · **{len(shared)} shared across multiple tables**\nNames are compared case-insensitively; different words/plurals remain separate.",
        color=discord.Color.from_rgb(57, 75, 111),
    )
    for table_name, names in tables.items():
        exclusive = sorted((display_names[k] for k in names if counts[k] == 1), key=str.casefold)
        shared_here = sorted((display_names[k] for k in names if counts[k] > 1), key=str.casefold)
        lines = [
            f"**Ingredients:** {len(names)} · **Shared:** {len(shared_here)} · **Exclusive:** {len(exclusive)}",
            "Exclusive: " + (", ".join(exclusive[:18]) if exclusive else "None"),
        ]
        if len(exclusive) > 18:
            lines.append(f"…and {len(exclusive) - 18} more exclusive ingredients")
        embed.add_field(name=table_name[:256], value="\n".join(lines)[:1024], inline=False)
    if shared:
        embed.add_field(name="Most shared ingredients", value=", ".join(shared[:40])[:1024], inline=False)
    return embed


def validate_recipe_data(data: dict[str, Any]):
    """Return cautious findings; never auto-correct or merge user-authored data."""
    findings = []
    ingredient_locations = defaultdict(list)
    for table in data.get("tables", []):
        table_name = str(table.get("name", "")).strip()
        if not table_name:
            findings.append({"severity": "error", "message": "A crafting table has a blank name."})
        seen_recipe_names = set()
        for recipe in table.get("recipes", []):
            recipe_name = str(recipe.get("name", "")).strip()
            if not recipe_name:
                findings.append({"severity": "error", "message": f"{table_name}: a recipe has a blank name."})
            folded_recipe = recipe_name.casefold()
            if folded_recipe and folded_recipe in seen_recipe_names:
                findings.append({"severity": "warning", "message": f"{table_name}: more than one recipe is named '{recipe_name}'."})
            seen_recipe_names.add(folded_recipe)
            ingredients = recipe.get("ingredients") or []
            if not ingredients:
                findings.append({"severity": "warning", "message": f"{table_name} / {recipe_name or 'Unnamed recipe'}: no ingredients are recorded."})
            for item in ingredients:
                if not isinstance(item, (list, tuple)) or len(item) != 2:
                    findings.append({"severity": "error", "message": f"{table_name} / {recipe_name}: malformed ingredient entry {item!r}."})
                    continue
                name, quantity = item
                label = str(name).strip()
                if not label:
                    findings.append({"severity": "error", "message": f"{table_name} / {recipe_name}: blank ingredient name."})
                    continue
                try:
                    valid_quantity = int(quantity) >= 1
                except (TypeError, ValueError):
                    valid_quantity = False
                if not valid_quantity:
                    findings.append({"severity": "error", "message": f"{table_name} / {recipe_name}: '{label}' has an invalid quantity ({quantity!r})."})
                ingredient_locations[label.casefold()].append((label, table_name, recipe_name))
    # Similar names are only flagged for human review; the bot never merges them.
    distinct = {}
    for entries in ingredient_locations.values():
        if entries:
            distinct.setdefault(entries[0][0], None)
    names = list(distinct)
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            if left.casefold() == right.casefold():
                continue
            if SequenceMatcher(None, left.casefold(), right.casefold()).ratio() >= 0.94:
                findings.append({"severity": "warning", "message": f"Possible spelling variation: '{left}' vs '{right}'. Review manually; neither name was changed."})
    if not findings:
        findings.append({"severity": "success", "message": "No obvious recipe-data issues found."})
    return findings


def validation_embed(findings: list[dict[str, str]]) -> discord.Embed:
    counts = Counter(item["severity"] for item in findings)
    embed = discord.Embed(
        title="🧪 Recipe Data Check",
        description=f"**{counts['error']} error(s)** · **{counts['warning']} warning(s)** · **{counts['success']} clean result(s)**\nThis checker never changes recipe data.",
        color=discord.Color.orange() if counts["error"] or counts["warning"] else discord.Color.green(),
    )
    for item in findings[:20]:
        icon = {"error": "🔴", "warning": "🟠", "success": "🟢"}.get(item["severity"], "ℹ️")
        embed.add_field(name=f"{icon} {item['severity'].title()}", value=item["message"][:1024], inline=False)
    if len(findings) > 20:
        embed.set_footer(text=f"Showing 20 of {len(findings)} findings.")
    return embed


def recipes_csv_bytes(data: dict[str, Any]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["Crafting Table", "Recipe", "Ingredient", "Quantity", "Occurrence"])
    for table in data.get("tables", []):
        for recipe in table.get("recipes", []):
            for occurrence, (ingredient, quantity) in enumerate(recipe.get("ingredients") or [], start=1):
                writer.writerow([table.get("name", ""), recipe.get("name", ""), ingredient, quantity, occurrence])
    return stream.getvalue().encode("utf-8-sig")


def recipes_xlsx_bytes(data: dict[str, Any]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Ingredients"
    sheet.append(["Crafting Table", "Recipe", "Ingredient", "Quantity", "Occurrence"])
    for table in data.get("tables", []):
        for recipe in table.get("recipes", []):
            for occurrence, (ingredient, quantity) in enumerate(recipe.get("ingredients") or [], start=1):
                sheet.append([table.get("name", ""), recipe.get("name", ""), ingredient, quantity, occurrence])
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="394B6F")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column, width in {"A": 24, "B": 28, "C": 30, "D": 12, "E": 14}.items():
        sheet.column_dimensions[column].width = width
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()
