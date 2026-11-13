import io
import json
import logging
import os
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

# Load deployment-provided .env values before reading the Discord token.
env_file = Path(__file__).with_name(".env")
if env_file.is_file():
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)

import discord
from discord import app_commands
from discord.ext import commands

from crafting import (
    OVERRIDE_FILE, CraftingDirectoryView, create_backup, find_matches,
    load_recipe_data, parse_ingredients, save_recipe_data, search_embed,
)

PROJECT_NAME = "FiveM Crafting Directory"
BASE_DIR = Path(__file__).resolve().parent
STATS_FILE = BASE_DIR / "stats.json"
REPORTS_FILE = BASE_DIR / "reports.json"
LOG_FILE = BASE_DIR / "bot.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
logger = logging.getLogger("crafting-bot")
BOT_INTENTS = discord.Intents.default()


def read_json(path: Path, default):
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, OSError):
        logger.exception("Could not read %s; using defaults", path.name)
        return default


def write_json(path: Path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def record_usage(kind: str, term: str | None = None):
    stats = read_json(STATS_FILE, {"commands": 0, "searches": 0, "terms": {}, "tables": {}})
    stats["commands"] = int(stats.get("commands", 0)) + 1
    if kind == "search":
        stats["searches"] = int(stats.get("searches", 0)) + 1
        if term:
            terms = stats.setdefault("terms", {})
            terms[term[:60]] = int(terms.get(term[:60], 0)) + 1
    write_json(STATS_FILE, stats)


def record_table_usage(table_name: str):
    stats = read_json(STATS_FILE, {"commands": 0, "searches": 0, "terms": {}, "tables": {}})
    tables = stats.setdefault("tables", {})
    tables[table_name] = int(tables.get(table_name, 0)) + 1
    write_json(STATS_FILE, stats)


def is_guild_admin(interaction: discord.Interaction) -> bool:
    return bool(interaction.guild and interaction.user.guild_permissions.manage_guild)


class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"FiveM Crafting Directory bot is online.")

    def log_message(self, format, *args):
        return


class ResilientHTTPServer(HTTPServer):
    allow_reuse_address = True


def run_web_server():
    try:
        server = ResilientHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "10000"))), KeepAliveHandler)
        server.serve_forever()
    except OSError as exc:
        logger.warning("Keepalive endpoint unavailable: %s", exc)


threading.Thread(target=run_web_server, daemon=True).start()


class CraftingBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=BOT_INTENTS)
        self.recipe_data = None

    async def setup_hook(self):
        self.recipe_data = load_recipe_data()
        synced = await self.tree.sync()
        count = sum(len(table.get("recipes", [])) for table in self.recipe_data["tables"])
        logger.info("Registered %s slash command(s). Loaded %s table(s) and %s recipe(s).", len(synced), len(self.recipe_data["tables"]), count)


bot = CraftingBot()


def refresh_recipe_data():
    bot.recipe_data = load_recipe_data()


@bot.event
async def on_ready():
    logger.info("%s online as %s | guilds connected: %s", PROJECT_NAME, bot.user, len(bot.guilds))


@bot.tree.command(name="crafting", description="Open your private FiveM crafting directory.")
@app_commands.describe(search="Optional: search by recipe, ingredient, tool, or table name.")
async def crafting_command(interaction: discord.Interaction, search: str | None = None):
    if bot.recipe_data is None:
        await interaction.response.send_message("The crafting directory is still loading. Try again shortly.", ephemeral=True)
        return
    record_usage("search" if search else "open", search)
    if search and search.strip():
        await interaction.response.send_message(embed=search_embed(bot.recipe_data, search.strip()), ephemeral=True)
        return
    view = CraftingDirectoryView(interaction.user.id, bot.recipe_data, on_table_selected=record_table_usage)
    await interaction.response.send_message(embed=view.current_embed(), view=view, ephemeral=True)


@bot.tree.command(name="crafting-search", description="Search recipes, ingredients, or tools; optionally filter by table.")
@app_commands.describe(query="Recipe, ingredient, tool, or table to search for.", table="Optional crafting table filter.")
async def crafting_search_command(interaction: discord.Interaction, query: str, table: str | None = None):
    record_usage("search", query)
    await interaction.response.send_message(embed=search_embed(bot.recipe_data, query, table), ephemeral=True)


@bot.tree.command(name="crafting-help", description="Show CraftingBot commands and tips.")
async def crafting_help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="📘 CraftingBot Help", description="A private FiveM roleplay crafting reference.", color=discord.Color.from_rgb(57, 75, 111))
    embed.add_field(name="/crafting", value="Open the interactive table and recipe directory.", inline=False)
    embed.add_field(name="/crafting search", value="Search from the main command.", inline=False)
    embed.add_field(name="/crafting-search", value="Search by recipe, ingredient, or tool, with an optional table filter.", inline=False)
    embed.add_field(name="/crafting-stats", value="View anonymous usage totals.", inline=False)
    embed.add_field(name="/crafting-report", value="Privately report missing or incorrect recipe information.", inline=False)
    embed.add_field(name="/crafting-admin", value="Manage recipes, review reports, and create backups (Manage Server permission required).", inline=False)
    embed.set_footer(text="Directory and search replies are private to you.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="crafting-stats", description="View CraftingBot usage statistics.")
async def crafting_stats_command(interaction: discord.Interaction):
    stats = read_json(STATS_FILE, {"commands": 0, "searches": 0, "terms": {}})
    top = sorted(stats.get("terms", {}).items(), key=lambda item: item[1], reverse=True)[:5]
    top_text = "\n".join(f"• {term} — {count}" for term, count in top) or "No searches recorded yet."
    popular_tables = sorted(stats.get("tables", {}).items(), key=lambda item: item[1], reverse=True)[:5]
    table_text = "\n".join(f"• {name} — {count}" for name, count in popular_tables) or "No table selections recorded yet."
    embed = discord.Embed(title="📊 CraftingBot Usage", color=discord.Color.from_rgb(57, 75, 111))
    embed.add_field(name="Commands used", value=str(stats.get("commands", 0)))
    embed.add_field(name="Searches", value=str(stats.get("searches", 0)))
    embed.add_field(name="Popular searches", value=top_text, inline=False)
    embed.add_field(name="Popular crafting tables", value=table_text, inline=False)
    embed.set_footer(text="Aggregate totals only; search message content is not retained.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="crafting-report", description="Privately report a missing or incorrect crafting entry.")
@app_commands.describe(details="Describe the table, recipe, or ingredient that needs attention.")
async def crafting_report_command(interaction: discord.Interaction, details: str):
    reports = read_json(REPORTS_FILE, [])
    report_id = len(reports) + 1
    reports.append({
        "id": report_id,
        "guild_id": interaction.guild_id,
        "user_id": interaction.user.id,
        "details": details[:1500],
        "created_at": discord.utils.utcnow().isoformat(),
        "status": "open",
    })
    write_json(REPORTS_FILE, reports)
    logger.info("Recipe report #%s submitted in guild %s", report_id, interaction.guild_id)
    await interaction.response.send_message(f"Your report **#{report_id}** has been saved for server administrators.", ephemeral=True)


admin_group = app_commands.Group(name="crafting-admin", description="Manage the FiveM crafting directory.")


@admin_group.command(name="add-table", description="Add a crafting table.")
@app_commands.default_permissions(manage_guild=True)
async def admin_add_table(interaction: discord.Interaction, table_name: str):
    if not is_guild_admin(interaction):
        await interaction.response.send_message("Manage Server permission is required.", ephemeral=True)
        return
    name = table_name.strip()
    data = load_recipe_data()
    if not name or any(t["name"].casefold() == name.casefold() for t in data["tables"]):
        await interaction.response.send_message("Enter a unique table name.", ephemeral=True)
        return
    data["tables"].append({"name": name, "recipes": []})
    save_recipe_data(data)
    refresh_recipe_data()
    await interaction.response.send_message(f"Added **{name}**. An automatic backup was created.", ephemeral=True)


@admin_group.command(name="add-recipe", description="Add a recipe to an existing table.")
@app_commands.default_permissions(manage_guild=True)
async def admin_add_recipe(interaction: discord.Interaction, table_name: str, recipe_name: str, ingredients: str, tools: str | None = None):
    if not is_guild_admin(interaction):
        await interaction.response.send_message("Manage Server permission is required.", ephemeral=True)
        return
    try:
        parsed = parse_ingredients(ingredients)
    except ValueError as exc:
        await interaction.response.send_message(str(exc), ephemeral=True)
        return
    data = load_recipe_data()
    table = next((t for t in data["tables"] if t["name"].casefold() == table_name.casefold()), None)
    if table is None:
        await interaction.response.send_message("Table not found. Check its exact name or add it first.", ephemeral=True)
        return
    name = recipe_name.strip()
    if not name:
        await interaction.response.send_message("Recipe name cannot be empty.", ephemeral=True)
        return
    table["recipes"].append({"name": name, "ingredients": parsed, "tools": [x.strip() for x in (tools or "").split(",") if x.strip()], "review": "Added by server administrator", "source": "CraftingBot admin command"})
    save_recipe_data(data)
    refresh_recipe_data()
    await interaction.response.send_message(f"Added **{name}** to **{table['name']}**. Duplicate ingredients are retained.", ephemeral=True)


@admin_group.command(name="edit-recipe", description="Edit a recipe name, ingredients, or tools.")
@app_commands.default_permissions(manage_guild=True)
async def admin_edit_recipe(interaction: discord.Interaction, table_name: str, recipe_name: str, new_name: str | None = None, ingredients: str | None = None, tools: str | None = None):
    if not is_guild_admin(interaction):
        await interaction.response.send_message("Manage Server permission is required.", ephemeral=True)
        return
    data = load_recipe_data()
    table = next((t for t in data["tables"] if t["name"].casefold() == table_name.casefold()), None)
    recipe = next((r for r in table["recipes"] if r["name"].casefold() == recipe_name.casefold()), None) if table else None
    if recipe is None:
        await interaction.response.send_message("Recipe not found in that table.", ephemeral=True)
        return
    if new_name is not None and new_name.strip():
        recipe["name"] = new_name.strip()
    if ingredients is not None:
        try:
            recipe["ingredients"] = parse_ingredients(ingredients)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
    if tools is not None:
        recipe["tools"] = [x.strip() for x in tools.split(",") if x.strip()]
    save_recipe_data(data)
    refresh_recipe_data()
    await interaction.response.send_message(f"Updated **{recipe['name']}**. An automatic backup was created.", ephemeral=True)


@admin_group.command(name="remove-recipe", description="Remove a recipe from a table.")
@app_commands.default_permissions(manage_guild=True)
async def admin_remove_recipe(interaction: discord.Interaction, table_name: str, recipe_name: str):
    if not is_guild_admin(interaction):
        await interaction.response.send_message("Manage Server permission is required.", ephemeral=True)
        return
    data = load_recipe_data()
    table = next((t for t in data["tables"] if t["name"].casefold() == table_name.casefold()), None)
    index = next((i for i, r in enumerate(table["recipes"]) if r["name"].casefold() == recipe_name.casefold()), None) if table else None
    if index is None:
        await interaction.response.send_message("Recipe not found in that table.", ephemeral=True)
        return
    removed = table["recipes"].pop(index)
    save_recipe_data(data)
    refresh_recipe_data()
    await interaction.response.send_message(f"Removed **{removed['name']}**. An automatic backup was created.", ephemeral=True)


@admin_group.command(name="backup", description="Create a manual backup of the current recipe directory.")
@app_commands.default_permissions(manage_guild=True)
async def admin_backup(interaction: discord.Interaction):
    if not is_guild_admin(interaction):
        await interaction.response.send_message("Manage Server permission is required.", ephemeral=True)
        return
    path = create_backup()
    await interaction.response.send_message(f"Backup created: {path.name}", ephemeral=True)


@admin_group.command(name="export", description="Download the current recipe directory as JSON.")
@app_commands.default_permissions(manage_guild=True)
async def admin_export(interaction: discord.Interaction):
    if not is_guild_admin(interaction):
        await interaction.response.send_message("Manage Server permission is required.", ephemeral=True)
        return
    payload = json.dumps(load_recipe_data(), ensure_ascii=False, indent=2).encode("utf-8")
    await interaction.response.send_message("Current recipe directory export:", file=discord.File(io.BytesIO(payload), filename="crafting-recipes-export.json"), ephemeral=True)


@admin_group.command(name="stats", description="View table and recipe totals.")
@app_commands.default_permissions(manage_guild=True)
async def admin_stats(interaction: discord.Interaction):
    if not is_guild_admin(interaction):
        await interaction.response.send_message("Manage Server permission is required.", ephemeral=True)
        return
    data = load_recipe_data()
    count = sum(len(t.get("recipes", [])) for t in data["tables"])
    lines = "\n".join(f"• {t['name']}: {len(t.get('recipes', []))} recipes" for t in data["tables"])
    embed = discord.Embed(title="Crafting Directory Admin", description=lines, color=discord.Color.from_rgb(57, 75, 111))
    embed.add_field(name="Tables", value=str(len(data["tables"])))
    embed.add_field(name="Recipes", value=str(count))
    embed.add_field(name="Runtime admin data", value="Active" if OVERRIDE_FILE.exists() else "Not created yet")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@admin_group.command(name="reports", description="Review the latest open recipe reports.")
@app_commands.default_permissions(manage_guild=True)
async def admin_reports(interaction: discord.Interaction):
    if not is_guild_admin(interaction):
        await interaction.response.send_message("Manage Server permission is required.", ephemeral=True)
        return
    reports = read_json(REPORTS_FILE, [])
    open_reports = [report for report in reports if report.get("status") == "open"][-10:]
    if not open_reports:
        await interaction.response.send_message("There are no open recipe reports.", ephemeral=True)
        return
    embed = discord.Embed(title="Open Crafting Reports", color=discord.Color.from_rgb(57, 75, 111))
    for report in reversed(open_reports):
        embed.add_field(name=f"Report #{report['id']}", value=f"{report.get('details', '')[:700]}\\nSubmitted: {report.get('created_at', 'unknown')}", inline=False)
    embed.set_footer(text="Use /crafting-admin resolve-report with a report ID when addressed.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@admin_group.command(name="resolve-report", description="Mark a recipe report as resolved.")
@app_commands.default_permissions(manage_guild=True)
async def admin_resolve_report(interaction: discord.Interaction, report_id: int):
    if not is_guild_admin(interaction):
        await interaction.response.send_message("Manage Server permission is required.", ephemeral=True)
        return
    reports = read_json(REPORTS_FILE, [])
    report = next((item for item in reports if item.get("id") == report_id), None)
    if report is None:
        await interaction.response.send_message("Report ID not found.", ephemeral=True)
        return
    report["status"] = "resolved"
    report["resolved_at"] = discord.utils.utcnow().isoformat()
    write_json(REPORTS_FILE, reports)
    await interaction.response.send_message(f"Marked report #{report_id} as resolved.", ephemeral=True)


bot.tree.add_command(admin_group)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    logger.error("Slash command failed: %s", error, exc_info=(type(error), error, error.__traceback__))
    if not interaction.response.is_done():
        await interaction.response.send_message("The command could not complete. The error has been logged for troubleshooting.", ephemeral=True)


if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise ValueError("DISCORD_BOT_TOKEN is required. Check the Discloud deployment environment.")
    bot.run(token)
