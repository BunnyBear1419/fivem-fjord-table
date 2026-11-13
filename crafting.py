"""Private FiveM crafting directory views and duplicate-safe recipe storage."""
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import discord

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "recipes.json"
OVERRIDE_FILE = BASE_DIR / "crafting-data.json"  # Runtime admin edits; excluded from deploy bundles.
BACKUP_DIR = BASE_DIR / "backups"


def load_recipe_data() -> dict[str, Any]:
    source = OVERRIDE_FILE if OVERRIDE_FILE.is_file() else DATA_FILE
    with source.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data.get("tables"), list):
        raise ValueError("Recipe data must contain a tables list")
    return data


def all_recipes(data: dict[str, Any]):
    return [(table["name"], recipe) for table in data["tables"] for recipe in table.get("recipes", [])]


def create_backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    source = OVERRIDE_FILE if OVERRIDE_FILE.is_file() else DATA_FILE
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    destination = BACKUP_DIR / f"crafting-backup-{stamp}.json"
    shutil.copy2(source, destination)
    return destination


def save_recipe_data(data: dict[str, Any]) -> Path:
    if not isinstance(data.get("tables"), list):
        raise ValueError("Recipe data must contain a tables list")
    create_backup()
    temporary = OVERRIDE_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(OVERRIDE_FILE)
    return OVERRIDE_FILE


def parse_ingredients(value: str) -> list[list[Any]]:
    """Parse comma-separated Item x2 values; repeated ingredients are never deduplicated."""
    parsed = []
    for part in value.split(","):
        item = part.strip()
        if not item:
            continue
        if " x" in item:
            name, quantity_text = item.rsplit(" x", 1)
            try:
                quantity = int(quantity_text.strip())
            except ValueError as exc:
                raise ValueError(f"Invalid quantity in '{item}'. Use Item x2.") from exc
        else:
            name, quantity = item, 1
        name = name.strip()
        if not name or quantity < 1:
            raise ValueError(f"Invalid ingredient '{item}'. Quantities must be at least 1.")
        parsed.append([name, quantity])
    if not parsed:
        raise ValueError("Enter at least one ingredient, e.g. Plastic bag x2, Powder x1")
    return parsed


def recipe_embed(table_name: str, recipe: dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(title=f"🧪 {recipe['name']}", description=f"**Crafting table:** {table_name}", color=discord.Color.from_rgb(91, 119, 190))
    ingredients = recipe.get("ingredients") or []
    if ingredients:
        embed.add_field(name="Required ingredients", value="\n".join(f"• **{name}** × {quantity}" for name, quantity in ingredients)[:1024], inline=False)
    tools = recipe.get("tools") or []
    if tools:
        embed.add_field(name="Tools (not consumed)", value=", ".join(tools)[:1024], inline=False)
    if not ingredients:
        embed.add_field(name="Recipe data", value="This entry needs verification against its original in-game screenshot.", inline=False)
    embed.set_footer(text="FiveM roleplay reference • Verify against your server's current recipe")
    return embed


class CraftingDirectoryView(discord.ui.View):
    def __init__(self, owner_id: int, data: dict[str, Any]):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.tables = data["tables"]
        self.table_index = 0
        self.recipe_page = 0
        self._refresh_selects()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This private crafting menu belongs to someone else. Open your own private menu with the crafting command.", ephemeral=True)
            return False
        return True

    def _refresh_selects(self):
        self.clear_items()
        table_options = [discord.SelectOption(label=t["name"][:100], value=str(i), default=i == self.table_index) for i, t in enumerate(self.tables[:25])]
        table_select = discord.ui.Select(placeholder="Choose a crafting table", options=table_options or [discord.SelectOption(label="No tables available", value="none")], row=0)
        table_select.callback = self._choose_table
        self.add_item(table_select)
        table = self.tables[self.table_index] if self.tables else {"recipes": []}
        recipes = table.get("recipes", [])
        pages = max(1, (len(recipes) + 24) // 25)
        self.recipe_page = min(self.recipe_page, pages - 1)
        start = self.recipe_page * 25
        options = [discord.SelectOption(label=r["name"][:100], value=str(start + i)) for i, r in enumerate(recipes[start:start + 25])]
        recipe_select = discord.ui.Select(placeholder="Choose a recipe", options=options or [discord.SelectOption(label="No recipes available", value="none")], disabled=not bool(options), row=1)
        recipe_select.callback = self._choose_recipe
        self.add_item(recipe_select)
        prev = discord.ui.Button(label="◀ Previous", style=discord.ButtonStyle.secondary, disabled=self.recipe_page == 0, row=2)
        prev.callback = self._previous_page
        self.add_item(prev)
        nxt = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary, disabled=self.recipe_page + 1 >= pages, row=2)
        nxt.callback = self._next_page
        self.add_item(nxt)

    def current_embed(self):
        if not self.tables:
            return discord.Embed(title="FiveM Crafting Directory", description="No crafting tables have been added yet.", color=discord.Color.orange())
        table = self.tables[self.table_index]
        pages = max(1, (len(table.get("recipes", [])) + 24) // 25)
        embed = discord.Embed(title="🛠️ FiveM Crafting Directory", description=f"**Table:** {table['name']}\n**Recipes:** {len(table.get('recipes', []))}\nChoose a recipe to see its ingredients and tools.", color=discord.Color.from_rgb(57, 75, 111))
        embed.set_footer(text=f"Recipe page {self.recipe_page + 1}/{pages} • Private menu")
        return embed

    async def _choose_table(self, interaction):
        self.table_index = int(interaction.data["values"][0])
        self.recipe_page = 0
        self._refresh_selects()
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    async def _choose_recipe(self, interaction):
        table = self.tables[self.table_index]
        recipe = table["recipes"][int(interaction.data["values"][0])]
        await interaction.response.edit_message(embed=recipe_embed(table["name"], recipe), view=self)

    async def _previous_page(self, interaction):
        self.recipe_page = max(0, self.recipe_page - 1)
        self._refresh_selects()
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    async def _next_page(self, interaction):
        table = self.tables[self.table_index]
        last = max(0, (len(table.get("recipes", [])) - 1) // 25)
        self.recipe_page = min(last, self.recipe_page + 1)
        self._refresh_selects()
        await interaction.response.edit_message(embed=self.current_embed(), view=self)


def find_matches(data: dict[str, Any], query: str, table_filter: str | None = None):
    needle = query.casefold().strip()
    matches = []
    for table_name, recipe in all_recipes(data):
        if table_filter and table_filter.casefold() not in table_name.casefold():
            continue
        ingredients = recipe.get("ingredients") or []
        tools = recipe.get("tools") or []
        searchable = " ".join([recipe.get("name", ""), table_name] + [str(x[0]) for x in ingredients] + [str(x) for x in tools]).casefold()
        if needle in searchable:
            matches.append((table_name, recipe))
    return matches


def search_embed(data: dict[str, Any], query: str, table_filter: str | None = None) -> discord.Embed:
    matches = find_matches(data, query, table_filter)
    description = f"Found **{len(matches)}** matching recipe(s)."
    if table_filter:
        description += f"\n**Table filter:** {table_filter}"
    embed = discord.Embed(title=f"🔎 Crafting search: {query[:180]}", description=description, color=discord.Color.from_rgb(57, 75, 111))
    for table_name, recipe in matches[:10]:
        items = recipe.get("ingredients") or []
        summary = ", ".join(f"{name} ×{qty}" for name, qty in items) or "Ingredients need review"
        tools = recipe.get("tools") or []
        if tools:
            summary += "\nTools: " + ", ".join(tools)
        embed.add_field(name=f"{recipe['name']} · {table_name}"[:256], value=summary[:1024], inline=False)
    if len(matches) > 10:
        embed.set_footer(text=f"Showing first 10 of {len(matches)} results. Narrow your search or filter by table.")
    return embed
