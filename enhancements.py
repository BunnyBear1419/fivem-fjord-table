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
            if SequenceMatcher(None, left.casefold(), right.casefold()).ratio() >= 0.75:
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


# --- Crafting Explorer and Planner extensions ---

def ensure_stable_ids(data: dict[str, Any], persistable: bool = True):
    """Add stable IDs without changing ingredient rows or names."""
    import uuid
    namespace = uuid.UUID("a03e62a5-21f4-49a5-92de-92b9b94a7a6e")
    for ti, table in enumerate(data.get("tables", [])):
        if not table.get("id"):
            table["id"] = str(uuid.uuid5(namespace, f"table:{ti}:{table.get('name','')}"))
        for ri, recipe in enumerate(table.get("recipes", [])):
            if not recipe.get("id"):
                recipe["id"] = str(uuid.uuid5(namespace, f"recipe:{table['id']}:{ri}:{recipe.get('name','')}"))
    return data


def dependency_chain(data: dict[str, Any], item_name: str, max_depth: int = 8):
    """Trace recipe outputs backward to their ingredient recipes, safely stopping cycles."""
    ensure_stable_ids(data)
    by_output = {}
    for table in data.get("tables", []):
        for recipe in table.get("recipes", []):
            by_output.setdefault(str(recipe.get("name", "")).casefold().strip(), []).append((table, recipe))
    visited = set()
    def walk(item, depth):
        key = str(item).casefold().strip()
        if not key or depth >= max_depth or key in visited:
            return {"item": item, "cycle": key in visited, "recipes": []}
        visited.add(key)
        matches = []
        for table, recipe in by_output.get(key, []):
            ingredients = []
            for name, qty in recipe.get("ingredients") or []:
                ingredients.append({"name": str(name), "quantity": int(qty), "source": walk(name, depth + 1)})
            matches.append({"table": table.get("name", ""), "recipe": recipe.get("name", ""), "ingredients": ingredients})
        visited.remove(key)
        return {"item": item, "cycle": False, "recipes": matches}
    return walk(item_name, 0)


def dependency_lines(node, depth=0, limit=60):
    lines = []
    prefix = "  " * min(depth, 8)
    if node.get("cycle"):
        return [f"{prefix}↳ {node['item']} (cycle stopped)"]
    recipes = node.get("recipes") or []
    if not recipes:
        return [f"{prefix}• {node['item']} (no recipe output found; treated as base item)"]
    for entry in recipes:
        lines.append(f"{prefix}🛠️ {entry['recipe']} — {entry['table']}")
        for ingredient in entry["ingredients"]:
            lines.append(f"{prefix}  • {ingredient['name']} ×{ingredient['quantity']}")
            lines.extend(dependency_lines(ingredient["source"], depth + 2, limit)[:max(0, limit-len(lines))])
            if len(lines) >= limit:
                lines.append("… dependency view shortened")
                return lines
    return lines


def parse_inventory(text: str):
    """Parse an inventory string, retaining repeated rows until totals are calculated."""
    from collections import defaultdict
    totals = defaultdict(int)
    for name, quantity in parse_simple_items(text):
        totals[name] += quantity
    return dict(totals)


def parse_simple_items(text: str):
    import re
    parsed = []
    for part in re.split(r"[,;\n]+", text or ""):
        item = part.strip()
        if not item:
            continue
        match = re.match(r"^(.*?)\s+[x×]\s*(\d+)$", item, re.IGNORECASE)
        if match:
            name, quantity = match.group(1).strip(), int(match.group(2))
        else:
            name, quantity = item, 1
        if not name or quantity < 1:
            raise ValueError(f"Invalid inventory entry: {item}")
        parsed.append((name, quantity))
    if not parsed:
        raise ValueError("Enter at least one item, for example: Plastic x5, Wire x10")
    return parsed


def inventory_plan(data: dict[str, Any], table_name: str, recipe_name: str, target_batches: int, inventory_text: str):
    if not isinstance(target_batches, int) or not 1 <= target_batches <= 999:
        raise ValueError("Target batches must be between 1 and 999.")
    required = calculate_recipe_ingredients(data, table_name, recipe_name, target_batches)["ingredients"]
    stock = parse_inventory(inventory_text)
    available_batches = None
    for name, per_target in required.items():
        per_batch = per_target // target_batches
        possible = stock.get(name, 0) // per_batch if per_batch else 999
        available_batches = possible if available_batches is None else min(available_batches, possible)
    available_batches = available_batches or 0
    missing = {name: max(0, quantity-stock.get(name, 0)) for name, quantity in required.items() if quantity > stock.get(name, 0)}
    return {"available_batches": min(available_batches, 999), "target_batches": target_batches, "required": required, "stock": stock, "missing": missing}


def multi_recipe_plan(data: dict[str, Any], requests: list[tuple[str, str, int]]):
    from collections import defaultdict
    totals = defaultdict(int)
    tools = set()
    selected = []
    for table, recipe, batches in requests:
        result = calculate_recipe_ingredients(data, table, recipe, batches)
        selected.append(f"{result['table']} — {result['recipe']} ×{batches}")
        for name, quantity in result["ingredients"].items():
            totals[name] += quantity
        tools.update(result["tools"])
    return {"selected": selected, "ingredients": dict(totals), "tools": sorted(tools, key=str.casefold)}


def advanced_search(data: dict[str, Any], query: str = "", table_filter: str = "", ingredient_filter: str = "", tool_filter: str = "", min_ingredients: int = 0):
    if not isinstance(min_ingredients, int) or not 0 <= min_ingredients <= 999:
        raise ValueError("Minimum ingredient rows must be between 0 and 999.")
    results = []
    for table, recipe in ((t, r) for t in data.get("tables", []) for r in t.get("recipes", [])):
        ingredients = recipe.get("ingredients") or []
        tools = recipe.get("tools") or []
        if table_filter and table_filter.casefold() not in table.get("name", "").casefold():
            continue
        if ingredient_filter and not any(ingredient_filter.casefold() in str(x[0]).casefold() for x in ingredients):
            continue
        if tool_filter and not any(tool_filter.casefold() in str(x).casefold() for x in tools):
            continue
        if len(ingredients) < min_ingredients:
            continue
        haystack = " ".join([table.get("name", ""), recipe.get("name", "")] + [str(x[0]) for x in ingredients] + [str(x) for x in tools]).casefold()
        if query and query.casefold() not in haystack:
            continue
        results.append((table.get("name", ""), recipe))
    return results


def recipe_comparison(data: dict[str, Any], table_a: str, recipe_a: str, table_b: str, recipe_b: str):
    a = calculate_recipe_ingredients(data, table_a, recipe_a, 1)
    b = calculate_recipe_ingredients(data, table_b, recipe_b, 1)
    left = {str(k).casefold(): (k, v) for k, v in a["ingredients"].items()}
    right = {str(k).casefold(): (k, v) for k, v in b["ingredients"].items()}
    common = sorted((left[k][0] for k in left.keys() & right.keys()), key=str.casefold)
    only_a = sorted((left[k][0] for k in left.keys() - right.keys()), key=str.casefold)
    only_b = sorted((right[k][0] for k in right.keys() - left.keys()), key=str.casefold)
    return {"a": a, "b": b, "shared": common, "only_a": only_a, "only_b": only_b}


def merge_recipe_import(current: dict[str, Any], incoming: dict[str, Any], mode: str = "skip"):
    """Merge imported tables/recipes. Name conflicts are skipped or replaced only by explicit choice."""
    if not isinstance(incoming, dict) or not isinstance(incoming.get("tables"), list):
        raise ValueError("Import must be a JSON object containing a tables list.")
    ensure_stable_ids(current)
    ensure_stable_ids(incoming)
    result = __import__("copy").deepcopy(current)
    added_tables = added_recipes = skipped = replaced = 0
    for new_table in incoming["tables"]:
        target = next((t for t in result["tables"] if t["name"].casefold().strip() == str(new_table.get("name","")).casefold().strip()), None)
        if target is None:
            result["tables"].append(new_table)
            added_tables += 1
            added_recipes += len(new_table.get("recipes", []))
            continue
        for new_recipe in new_table.get("recipes", []):
            existing = next((r for r in target.get("recipes", []) if r["name"].casefold().strip() == str(new_recipe.get("name","")).casefold().strip()), None)
            if existing is None:
                target.setdefault("recipes", []).append(new_recipe)
                added_recipes += 1
            elif mode == "replace":
                new_recipe["id"] = existing.get("id", new_recipe.get("id"))
                target["recipes"][target["recipes"].index(existing)] = new_recipe
                replaced += 1
            else:
                skipped += 1
    findings = validate_recipe_data(result)
    errors = [f for f in findings if f["severity"] == "error"]
    if errors:
        raise ValueError("Import validation failed: " + "; ".join(x["message"] for x in errors[:5]))
    return result, {"tables_added": added_tables, "recipes_added": added_recipes, "skipped": skipped, "replaced": replaced, "warnings": sum(x["severity"] == "warning" for x in findings)}


def analytics_embed(data: dict[str, Any], stats: dict[str, Any]):
    embed = discord.Embed(title="📈 Crafting Analytics", color=discord.Color.from_rgb(57, 75, 111))
    total = sum(len(t.get("recipes", [])) for t in data.get("tables", []))
    embed.description = f"**{len(data.get('tables', []))} tables** · **{total} recipes** · **{sum(len(r.get('ingredients') or []) for t in data.get('tables', []) for r in t.get('recipes', []))} ingredient rows**"
    embed.add_field(name="Menu opens", value=str(stats.get("commands", 0)))
    embed.add_field(name="Searches", value=str(stats.get("searches", 0)))
    top_tables = sorted(stats.get("tables", {}).items(), key=lambda x: x[1], reverse=True)[:8]
    embed.add_field(name="Most browsed tables", value="\\n".join(f"• {name}: {count}" for name, count in top_tables) or "No usage recorded.", inline=False)
    top_terms = sorted(stats.get("terms", {}).items(), key=lambda x: x[1], reverse=True)[:8]
    embed.add_field(name="Popular searches", value="\\n".join(f"• {name}: {count}" for name, count in top_terms) or "No searches recorded.", inline=False)
    return embed
