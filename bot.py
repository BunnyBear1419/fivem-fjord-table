import hashlib
import io
import json
import logging
import os
import re
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
from discord.ext import commands, tasks

from crafting import (
    OVERRIDE_FILE, BACKUP_DIR, CraftingDirectoryView, create_backup, load_recipe_data,
    parse_ingredients, save_recipe_data, search_embed, ingredient_usage_embed,
    build_ingredient_directory, ingredient_directory_embed, ingredient_directory_document,
)
from storage import atomic_write_json, read_json as storage_read_json, file_lock
from hybrid_ai import answer_question as hybrid_ai_answer, is_configured as hybrid_ai_is_configured
from enhancements import (
    calculate_recipe_ingredients, recipe_shopping_embed, table_comparison_embed,
    validate_recipe_data, validation_embed, recipes_csv_bytes, recipes_xlsx_bytes,
    ensure_stable_ids, dependency_chain, dependency_lines, inventory_plan,
    multi_recipe_plan, advanced_search, recipe_comparison, merge_recipe_import,
    analytics_embed, chat_recipe_search, related_table_search, parse_inventory, expanded_production_requirements, calculate_shop_price_query, calculate_raw_cocaine_requirements, calculate_weed_growing_requirements, calculate_inventory_limited_batches, inventory_quantity, parse_usable_item_sections, attach_location_recipe_warnings, validate_city_reference_data,
)

PROJECT_NAME = "Fjord Cartel Information"
BASE_DIR = Path(__file__).resolve().parent
STATS_FILE = BASE_DIR / "stats.json"
REPORTS_FILE = BASE_DIR / "reports.json"
HISTORY_FILE = BASE_DIR / "history.json"
INVENTORIES_FILE = BASE_DIR / "inventories.json"
SHOPPING_LISTS_FILE = BASE_DIR / "shopping-lists.json"
PLAYER_ACTIVITY_FILE = BASE_DIR / "player-activity.json"
ALIASES_FILE = BASE_DIR / "aliases.json"
AUDIT_FILE = BASE_DIR / "audit-log.json"
GUILD_PROFILES_FILE = BASE_DIR / "guild-profiles.json"
PROFILES_DIR = BASE_DIR / "profiles"
LOG_FILE = BASE_DIR / "bot.log"
COLOR = discord.Color.from_rgb(24, 112, 66)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(), RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")],
)
logger = logging.getLogger("crafting-bot")


def read_json(path: Path, default):
    return storage_read_json(path, default)


def write_json(path: Path, data):
    return atomic_write_json(path, data)


def recipe_fingerprint(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def record_usage(kind: str, term: str | None = None):
    with file_lock():
        stats = read_json(STATS_FILE, {"commands": 0, "searches": 0, "terms": {}, "tables": {}, "no_results": 0, "no_result_terms": {}})
        if kind != "no_result":
            stats["commands"] = int(stats.get("commands", 0)) + 1
        if kind == "search":
            stats["searches"] = int(stats.get("searches", 0)) + 1
            if term:
                terms = stats.setdefault("terms", {})
                terms[term[:60]] = int(terms.get(term[:60], 0)) + 1
                if len(terms) > 100:
                    stats["terms"] = dict(sorted(terms.items(), key=lambda item: item[1], reverse=True)[:100])
        elif kind == "no_result":
            stats["no_results"] = int(stats.get("no_results", 0)) + 1
            if term:
                terms = stats.setdefault("no_result_terms", {})
                terms[term[:60]] = int(terms.get(term[:60], 0)) + 1
                if len(terms) > 100:
                    stats["no_result_terms"] = dict(sorted(terms.items(), key=lambda item: item[1], reverse=True)[:100])
        write_json(STATS_FILE, stats)


def record_table_usage(table_name: str):
    with file_lock():
        stats = read_json(STATS_FILE, {"commands": 0, "searches": 0, "terms": {}, "tables": {}})
        tables = stats.setdefault("tables", {})
        tables[table_name[:100]] = int(tables.get(table_name[:100], 0)) + 1
        if len(tables) > 50:
            stats["tables"] = dict(sorted(tables.items(), key=lambda item: item[1], reverse=True)[:50])
        write_json(STATS_FILE, stats)


def record_audit_event(guild_id, actor_id: int, action: str, details: str):
    with file_lock():
        entries = read_json(AUDIT_FILE, [])
        entries.append({"guild_id": guild_id, "actor_id": actor_id, "action": action[:80], "details": details[:300], "created_at": discord.utils.utcnow().isoformat()})
        write_json(AUDIT_FILE, entries[-1000:])


def record_player_activity(guild_id, user_id: int, action: str, details: str = ""):
    """Keep a bounded, private-to-the-member activity trail for useful bot actions."""
    if user_id is None:
        return
    with file_lock():
        entries = read_json(PLAYER_ACTIVITY_FILE, [])
        entries.append({
            "guild_id": str(guild_id or "dm"),
            "user_id": str(user_id),
            "action": str(action)[:80],
            "details": str(details)[:120],
            "created_at": discord.utils.utcnow().isoformat(),
        })
        write_json(PLAYER_ACTIVITY_FILE, entries[-1000:])


def recent_activity_embed(guild_id, user_id: int):
    entries = [item for item in read_json(PLAYER_ACTIVITY_FILE, [])
               if item.get("guild_id") == str(guild_id or "dm") and item.get("user_id") == str(user_id)]
    embed = discord.Embed(
        title="🕘 My Recent Activity",
        description="Your latest bot searches and planning actions in this server. Only you can view this list.",
        color=COLOR,
    )
    for item in reversed(entries[-20:]):
        timestamp = str(item.get("created_at", "Unknown"))[:19].replace("T", " ")
        value = str(item.get("details") or "No extra details")
        embed.add_field(name=f"{item.get('action', 'Activity')} · {timestamp}", value=value[:300], inline=False)
    if not entries:
        embed.description += "\n\nNo activity has been recorded yet."
    embed.set_footer(text="FJORD CARTEL • PRIVATE MEMBER ACTIVITY")
    return embed


def _profile_path(guild_id: int, profile: str) -> Path:
    safe = "".join(ch for ch in str(profile) if ch.isalnum() or ch in "-_")[:40]
    if not safe:
        raise ValueError("Profile names may contain letters, numbers, hyphens and underscores.")
    return PROFILES_DIR / str(guild_id) / f"{safe}.json"


def record_recipe_change(before_data: dict, action: str, actor_id: int, summary: str, guild_id=None):
    """Keep the latest 30 reversible snapshots to bound runtime storage."""
    with file_lock():
        history = read_json(HISTORY_FILE, [])
        entry_id = max((int(item.get("id", 0)) for item in history), default=0) + 1
        history.append({
            "id": entry_id,
            "action": action,
            "actor_id": actor_id,
            "guild_id": guild_id,
            "summary": summary[:300],
            "created_at": discord.utils.utcnow().isoformat(),
            "snapshot": before_data,
        })
        write_json(HISTORY_FILE, history[-30:])
        record_audit_event(guild_id, actor_id, action, summary)
        return entry_id



def get_guild_recipe_data(guild_id):
    if guild_id is None:
        return bot.recipe_data or load_recipe_data()
    profiles = read_json(GUILD_PROFILES_FILE, {})
    selected = profiles.get(str(guild_id))
    if selected:
        path = _profile_path(guild_id, selected)
        if path.is_file():
            return ensure_stable_ids(json.loads(path.read_text(encoding="utf-8")))
    return bot.recipe_data or load_recipe_data()


def save_guild_recipe_data(guild_id, data):
    if guild_id is None:
        save_recipe_data(data)
        refresh_recipe_data()
        return
    profiles = read_json(GUILD_PROFILES_FILE, {})
    selected = profiles.get(str(guild_id))
    if selected:
        path = PROFILES_DIR / str(guild_id) / (str(selected) + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, ensure_stable_ids(data))
    else:
        save_recipe_data(data)
        refresh_recipe_data()


def guild_aliases(guild_id):
    return read_json(ALIASES_FILE, {}).get(str(guild_id or "dm"), {})

class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        application = globals().get("bot")
        ready = bool(application and application.is_ready())
        self.send_response(200 if ready else 503)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        message = b"FiveM Crafting Directory bot is online." if ready else b"FiveM Crafting Directory bot is starting or unavailable."
        self.wfile.write(message)

    def log_message(self, format, *args):
        return


class ResilientHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def run_web_server():
    try:
        server = ResilientHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "10000"))), KeepAliveHandler)
        server.serve_forever()
    except OSError as exc:
        logger.warning("Keepalive endpoint unavailable: %s", exc)


threading.Thread(target=run_web_server, daemon=True).start()


def help_embed():
    embed = discord.Embed(
        title="⚔️ Fjord Cartel Information",
        description="**FJORD CARTEL • MEMBER INFORMATION SYSTEM**\n\nWelcome to the private cartel directory. Choose a section below to browse recipes, match ingredients, and plan what the crew needs.",
        color=COLOR,
    )
    embed.add_field(name="Browse recipes", value="Choose a crafting table, then a recipe to view ingredients and tools.", inline=False)
    embed.add_field(name="Search", value="Find recipes by name, ingredient, tool, or table.", inline=False)
    embed.add_field(name="Find ingredient across tables", value="Enter an exact ingredient name to see where it is crafted, which ingredients make it, and every table/recipe that uses it. Similar spellings remain separate.", inline=False)
    embed.add_field(name="All ingredients", value="Browse the complete ingredient directory by name, table, recipe, and quantity. Download the full plain-text list.", inline=False)
    embed.add_field(name="Recipe shopping list", value="Choose a recipe and batch count to calculate the total ingredients needed.", inline=False)
    embed.add_field(name="Crafting table comparison", value="Compare shared ingredients and ingredients unique to each table.", inline=False)
    embed.add_field(name="Production chains", value="Trace an item's crafting dependencies back to base ingredients.", inline=False)
    embed.add_field(name="Inventory calculator", value="Calculate craftable batches from stock entered for one calculation.", inline=False)
    embed.add_field(name="My saved inventory", value="Save your ingredient stock privately, update it later, and reuse it for recipe plans.", inline=False)
    embed.add_field(name="Multi-recipe planner", value="Combine several recipes into one shopping list.", inline=False)
    embed.add_field(name="Advanced search", value="Filter by table, ingredient, tool, keyword, and ingredient count.", inline=False)
    embed.add_field(name="Item database", value="Open an item page showing where it is made and used.", inline=False)
    embed.add_field(name="Recipe comparison", value="Compare two recipes and their shared/exclusive ingredients.", inline=False)
    embed.add_field(name="Report an issue", value="Privately report a missing or incorrect entry with table and recipe details.", inline=False)
    embed.add_field(name="Admin tools", value="Manage tables and recipes, imports, exports, backups, reports, aliases, and server profiles. Available to all server members.", inline=False)
    embed.set_footer(text="FJORD CARTEL • PRIVATE MEMBER MENU")
    return embed


class SafeView(discord.ui.View):
    @discord.ui.button(label="Home", emoji="🏠", style=discord.ButtonStyle.success, row=4)
    async def home_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        owner_id = getattr(self, "owner_id", interaction.user.id)
        await interaction.response.edit_message(
            embed=dashboard_embed(),
            view=DashboardMenuView(owner_id),
        )

    async def on_error(self, interaction, error, item):
        logger.error("Discord view interaction failed (%s): %s", type(item).__name__, error, exc_info=(type(error), error, error.__traceback__))
        message = "That action could not be completed. The error was logged for troubleshooting."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            logger.exception("Could not send view error feedback to Discord.")


class SafeModal(discord.ui.Modal):
    async def on_error(self, interaction, error):
        logger.error("Discord modal submission failed (%s): %s", type(self).__name__, error, exc_info=(type(error), error, error.__traceback__))
        message = "That submission could not be completed. The error was logged for troubleshooting."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            logger.exception("Could not send modal error feedback to Discord.")


class CraftingBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.recipe_data = None
        self.guild_commands_cleaned = False

    async def setup_hook(self):
        self.recipe_data = ensure_stable_ids(load_recipe_data())
        # Sync the current global slash-command set.
        synced = await self.tree.sync()
        count = sum(len(table.get("recipes", [])) for table in self.recipe_data["tables"])
        logger.info("Synced %s global slash command(s). Loaded %s table(s) and %s recipe(s).", len(synced), len(self.recipe_data["tables"]), count)

    async def on_ready(self):
        logger.info("%s online as %s | guilds connected: %s", PROJECT_NAME, self.user, len(self.guilds))
        if not automatic_backup.is_running():
            automatic_backup.start()
        # Remove any legacy guild-specific copies created by older bot versions.
        if not self.guild_commands_cleaned:
            for guild in self.guilds:
                self.tree.clear_commands(guild=guild)
                await self.tree.sync(guild=guild)
            self.guild_commands_cleaned = True
            logger.info("Cleared legacy guild-specific slash commands.")


bot = CraftingBot()


def refresh_recipe_data():
    bot.recipe_data = ensure_stable_ids(load_recipe_data())


@tasks.loop(hours=24)
async def automatic_backup():
    try:
        path = create_backup()
        backups = sorted(path.parent.glob("crafting-backup-*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        for old in backups[25:]:
            old.unlink(missing_ok=True)
        logger.info("Automatic recipe backup created: %s", path.name)
    except Exception:
        logger.exception("Automatic recipe backup failed")


@automatic_backup.before_loop
async def before_automatic_backup():
    await bot.wait_until_ready()


class SearchModal(SafeModal, title="Search crafting recipes"):
    query = discord.ui.TextInput(label="What are you looking for?", placeholder="Recipe, ingredient, tool, or table", max_length=100)
    table = discord.ui.TextInput(label="Limit to a table (optional)", placeholder="Example: Glovebox Table", required=False, max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        term = self.query.value.strip()
        record_usage("search", term)
        await interaction.response.send_message(embed=search_embed(include_usable_item_recipes(get_guild_recipe_data(interaction.guild_id)), next((target for alias, target in guild_aliases(interaction.guild_id).items() if alias.casefold() == term.casefold()), term), self.table.value.strip() or None), ephemeral=True)


class IngredientLookupModal(SafeModal, title="Find ingredient across tables"):
    ingredient = discord.ui.TextInput(
        label="Exact ingredient name",
        placeholder="Example: Meth or Hydroclone Acid",
        max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction):
        ingredient = self.ingredient.value.strip()
        record_usage("search", f"ingredient:{ingredient}")
        await interaction.response.send_message(
            embed=ingredient_usage_embed(include_usable_item_recipes(get_guild_recipe_data(interaction.guild_id)), ingredient),
            ephemeral=True,
        )


class ReportModal(SafeModal, title="Report a recipe issue"):
    issue_type = discord.ui.TextInput(label="Issue type", placeholder="Missing recipe / wrong ingredient / wrong quantity / other", max_length=80)
    table = discord.ui.TextInput(label="Crafting table (optional)", placeholder="Exact table name, if known", required=False, max_length=100)
    recipe = discord.ui.TextInput(label="Recipe name (optional)", placeholder="Exact recipe name, if known", required=False, max_length=100)
    details = discord.ui.TextInput(label="What needs correcting or adding?", style=discord.TextStyle.paragraph, placeholder="Describe what is wrong or missing.", max_length=1200)

    async def on_submit(self, interaction: discord.Interaction):
        with file_lock():
            reports = read_json(REPORTS_FILE, [])
            report_id = max((int(item.get("id", 0)) for item in reports), default=0) + 1
            reports.append({
                "id": report_id,
                "guild_id": interaction.guild_id,
                "user_id": interaction.user.id,
                "issue_type": self.issue_type.value.strip(),
                "table": self.table.value.strip(),
                "recipe": self.recipe.value.strip(),
                "details": self.details.value.strip(),
                "created_at": discord.utils.utcnow().isoformat(),
                "status": "open",
            })
            write_json(REPORTS_FILE, reports[-500:])
        logger.info("Recipe report #%s submitted in guild %s", report_id, interaction.guild_id)
        await interaction.response.send_message(f"Your report **#{report_id}** has been saved for server administrators.", ephemeral=True)


class AdminActionModal(SafeModal):
    def __init__(self, action: str):
        self.action = action
        fields = {
            "add_table": ("Add crafting table", [("table_name", "New table name", True, 100)]),
            "add_recipe": ("Add recipe", [
                ("table_name", "Exact table name", True, 100),
                ("recipe_name", "Recipe name", True, 100),
                ("ingredients", "Ingredients: Item x2, Item x1", True, 1500),
                ("tools", "Tools, separated by commas (optional)", False, 500),
            ]),
            "edit_recipe": ("Edit recipe", [
                ("table_name", "Exact table name", True, 100),
                ("recipe_name", "Current recipe name", True, 100),
                ("new_name", "New name (optional)", False, 100),
                ("ingredients", "Replacement ingredients (optional)", False, 1500),
                ("tools", "Replacement tools (optional)", False, 500),
            ]),
            "remove_recipe": ("Remove recipe", [
                ("table_name", "Exact table name", True, 100),
                ("recipe_name", "Exact recipe name", True, 100),
            ]),
            "resolve_report": ("Resolve recipe report", [("report_id", "Report number", True, 10)]),
            "restore_history": ("Restore a previous version", [("history_id", "History entry number", True, 10)]),
        }
        title, inputs = fields[action]
        super().__init__(title=title)
        for key, label, required, limit in inputs:
            field = discord.ui.TextInput(label=label, required=required, max_length=limit, custom_id=key)
            setattr(self, key, field)
            self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction):
        data = ensure_stable_ids(get_guild_recipe_data(interaction.guild_id))
        before_data = json.loads(json.dumps(data, ensure_ascii=False))
        if self.action == "add_table":
            name = self.table_name.value.strip()
            if not name or any(t["name"].casefold() == name.casefold() for t in data["tables"]):
                await interaction.response.send_message("Enter a unique table name.", ephemeral=True)
                return
            data["tables"].append({"id": __import__("uuid").uuid4().hex, "name": name, "recipes": []})
            record_recipe_change(before_data, "add_table", interaction.user.id, f"Added table: {name}", interaction.guild_id)
            save_guild_recipe_data(interaction.guild_id, data)
            await interaction.response.send_message(f"Added **{name}**. An automatic backup and change-history entry were created.", ephemeral=True)
            return

        if self.action == "add_recipe":
            table = next((t for t in data["tables"] if t["name"].casefold() == self.table_name.value.strip().casefold()), None)
            if table is None:
                await interaction.response.send_message("Table not found. Check its exact name or add it first.", ephemeral=True)
                return
            try:
                ingredients = parse_ingredients(self.ingredients.value)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
            name = self.recipe_name.value.strip()
            table["recipes"].append({
                "id": __import__("uuid").uuid4().hex,
                "name": name, "ingredients": ingredients,
                "tools": [x.strip() for x in self.tools.value.split(",") if x.strip()],
                "review": "Added by server administrator", "source": "CraftingBot admin menu",
            })
            record_recipe_change(before_data, "add_recipe", interaction.user.id, f"Added {name} to {table['name']}", interaction.guild_id)
            record_audit_event(interaction.guild_id, interaction.user.id, "recipe_add", f"{name} in {table['name']}")
            save_guild_recipe_data(interaction.guild_id, data)
            await interaction.response.send_message(f"Added **{name}** to **{table['name']}**. Duplicate ingredients are retained.", ephemeral=True)
            return

        if self.action == "edit_recipe":
            table = next((t for t in data["tables"] if t["name"].casefold() == self.table_name.value.strip().casefold()), None)
            recipe = next((r for r in table["recipes"] if r["name"].casefold() == self.recipe_name.value.strip().casefold()), None) if table else None
            if recipe is None:
                await interaction.response.send_message("Recipe not found in that table.", ephemeral=True)
                return
            if self.new_name.value.strip():
                recipe["name"] = self.new_name.value.strip()
            if self.ingredients.value.strip():
                try:
                    recipe["ingredients"] = parse_ingredients(self.ingredients.value)
                except ValueError as exc:
                    await interaction.response.send_message(str(exc), ephemeral=True)
                    return
            if self.tools.value.strip():
                recipe["tools"] = [x.strip() for x in self.tools.value.split(",") if x.strip()]
            record_recipe_change(before_data, "edit_recipe", interaction.user.id, f"Edited {recipe['name']} in {table['name']}", interaction.guild_id)
            save_guild_recipe_data(interaction.guild_id, data)
            await interaction.response.send_message(f"Updated **{recipe['name']}**. An automatic backup and change-history entry were created.", ephemeral=True)
            return

        if self.action == "remove_recipe":
            table = next((t for t in data["tables"] if t["name"].casefold() == self.table_name.value.strip().casefold()), None)
            index = next((i for i, r in enumerate(table["recipes"]) if r["name"].casefold() == self.recipe_name.value.strip().casefold()), None) if table else None
            if index is None:
                await interaction.response.send_message("Recipe not found in that table.", ephemeral=True)
                return
            removed = table["recipes"].pop(index)
            record_recipe_change(before_data, "remove_recipe", interaction.user.id, f"Removed {removed['name']} from {table['name']}", interaction.guild_id)
            save_guild_recipe_data(interaction.guild_id, data)
            await interaction.response.send_message(f"Removed **{removed['name']}**. An automatic backup and change-history entry were created.", ephemeral=True)
            return

        if self.action == "restore_history":
            try:
                history_id = int(self.history_id.value.strip())
            except ValueError:
                await interaction.response.send_message("Enter a valid history entry number.", ephemeral=True)
                return
            history = read_json(HISTORY_FILE, [])
            entry = next((item for item in history if int(item.get("id", 0)) == history_id and item.get("guild_id") == interaction.guild_id), None)
            if not entry or not isinstance(entry.get("snapshot"), dict):
                await interaction.response.send_message("That history entry has no restorable snapshot.", ephemeral=True)
                return
            record_recipe_change(data, "restore", interaction.user.id, f"Restored before history entry #{history_id}", interaction.guild_id)
            save_guild_recipe_data(interaction.guild_id, entry["snapshot"])
            await interaction.response.send_message(f"Restored the snapshot from history entry **#{history_id}**. The state being replaced was also saved to history.", ephemeral=True)
            return

        if self.action == "resolve_report":
            try:
                report_id = int(self.report_id.value.strip())
            except ValueError:
                await interaction.response.send_message("Enter a valid report number.", ephemeral=True)
                return
            reports = read_json(REPORTS_FILE, [])
            report = next((item for item in reports if item.get("id") == report_id), None)
            if report is None:
                await interaction.response.send_message("Report number not found.", ephemeral=True)
                return
            report["status"] = "resolved"
            report["resolved_at"] = discord.utils.utcnow().isoformat()
            write_json(REPORTS_FILE, reports)
            await interaction.response.send_message(f"Marked report #{report_id} as resolved.", ephemeral=True)


class AliasManagerModal(SafeModal, title="Manage ingredient search aliases"):
    aliases = discord.ui.TextInput(label="One alias => exact ingredient name per line", style=discord.TextStyle.paragraph, placeholder="weed => Clean Weed Bud\ncloth => Cheesecloth", max_length=1800)

    async def on_submit(self, interaction):
        parsed = {}
        for line in self.aliases.value.splitlines():
            if not line.strip():
                continue
            if "=>" not in line:
                await interaction.response.send_message(f"Invalid line: {line[:100]}. Use alias => exact ingredient name.", ephemeral=True)
                return
            alias, target = [part.strip() for part in line.split("=>", 1)]
            if not alias or not target or len(alias) > 80 or len(target) > 100:
                await interaction.response.send_message("Aliases and target names must be non-empty and within the length limits.", ephemeral=True)
                return
            parsed[alias] = target
        if len(parsed) > 50:
            await interaction.response.send_message("A server can have at most 50 aliases.", ephemeral=True)
            return
        all_aliases = read_json(ALIASES_FILE, {})
        all_aliases[str(interaction.guild_id or "dm")] = parsed
        write_json(ALIASES_FILE, all_aliases)
        record_audit_event(interaction.guild_id, interaction.user.id, "aliases_update", f"Saved {len(parsed)} ingredient alias(es)")
        await interaction.response.send_message(f"Saved {len(parsed)} alias(es). Original recipe and ingredient names were not changed.", ephemeral=True)



class ProfileSelectModal(SafeModal, title="Switch server recipe profile"):
    profile = discord.ui.TextInput(label="Existing profile name", max_length=40)

    async def on_submit(self, interaction):
        if not interaction.guild_id:
            await interaction.response.send_message("Server profiles can only be selected inside a Discord server.", ephemeral=True)
            return
        try:
            path = _profile_path(interaction.guild_id, self.profile.value.strip())
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        if not path.is_file():
            available = sorted(item.stem for item in path.parent.glob("*.json")) if path.parent.exists() else []
            await interaction.response.send_message("Profile not found. Available: " + (", ".join(available) or "none"), ephemeral=True)
            return
        profiles = read_json(GUILD_PROFILES_FILE, {})
        profiles[str(interaction.guild_id)] = self.profile.value.strip()
        write_json(GUILD_PROFILES_FILE, profiles)
        record_audit_event(interaction.guild_id, interaction.user.id, "profile_switch", f"Activated profile {self.profile.value.strip()}")
        await interaction.response.send_message(f"Activated server recipe profile **{self.profile.value.strip()}**. New /dashboard sessions will use it.", ephemeral=True)


class ProfileCreateModal(SafeModal, title="Create a server recipe profile"):
    profile = discord.ui.TextInput(label="Profile name", placeholder="main, test, seasonal", max_length=40)

    async def on_submit(self, interaction):
        if not interaction.guild_id:
            await interaction.response.send_message("Server profiles can only be created inside a Discord server.", ephemeral=True)
            return
        try:
            path = _profile_path(interaction.guild_id, self.profile.value.strip())
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        if path.exists():
            await interaction.response.send_message("That profile already exists. Choose a different name.", ephemeral=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, get_guild_recipe_data(interaction.guild_id))
        profiles = read_json(GUILD_PROFILES_FILE, {})
        profiles[str(interaction.guild_id)] = self.profile.value.strip()
        write_json(GUILD_PROFILES_FILE, profiles)
        record_audit_event(interaction.guild_id, interaction.user.id, "profile_create", f"Created and activated profile {self.profile.value.strip()}")
        await interaction.response.send_message(f"Created and activated profile **{self.profile.value.strip()}** with a copy of the current recipe directory. This profile is now separate for this server.", ephemeral=True)


class AdminMenuView(SafeView):
    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        options = [
            discord.SelectOption(label="Import / merge recipe JSON", value="import_json", emoji="📥"),
            discord.SelectOption(label="View crafting analytics", value="analytics", emoji="📈"),
            discord.SelectOption(label="Add a crafting table", value="add_table", emoji="➕"),
            discord.SelectOption(label="Add a recipe", value="add_recipe", emoji="🧪"),
            discord.SelectOption(label="Edit a recipe", value="edit_recipe", emoji="✏️"),
            discord.SelectOption(label="Remove a recipe", value="remove_recipe", emoji="🗑️"),
            discord.SelectOption(label="Create a backup", value="backup", emoji="💾"),
            discord.SelectOption(label="Download latest backup", value="download_backup", emoji="⬇️"),
            discord.SelectOption(label="Export recipe data (JSON)", value="export", emoji="📤"),
            discord.SelectOption(label="Export ingredients (CSV)", value="export_csv", emoji="📄"),
            discord.SelectOption(label="Export ingredients (Excel)", value="export_xlsx", emoji="📊"),
            discord.SelectOption(label="Review spelling & data warnings", value="validate", emoji="🧪"),
            discord.SelectOption(label="View change history", value="history", emoji="🕘"),
            discord.SelectOption(label="Restore a previous version", value="restore_history", emoji="↩️"),
            discord.SelectOption(label="View directory statistics", value="stats", emoji="📊"),
            discord.SelectOption(label="System health check", value="health", emoji="🩺"),
            discord.SelectOption(label="Activity audit log", value="audit", emoji="🧾"),
            discord.SelectOption(label="Manage ingredient aliases", value="aliases", emoji="🏷️"),
            discord.SelectOption(label="Create server recipe profile", value="profile", emoji="🗂️"),
            discord.SelectOption(label="Switch server recipe profile", value="profile_switch", emoji="🔀"),
            discord.SelectOption(label="Review open reports", value="reports", emoji="📨"),
            discord.SelectOption(label="Resolve a report", value="resolve_report", emoji="✅"),
            discord.SelectOption(label="Back to main menu", value="back", emoji="↩️"),
        ]
        select = discord.ui.Select(placeholder="Choose an admin action", options=options)
        select.callback = self.choose_action
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This private menu belongs to someone else.", ephemeral=True)
            return False
        return True

    async def choose_action(self, interaction: discord.Interaction):
        action = interaction.data["values"][0]
        if action == "back":
            await interaction.response.edit_message(embed=help_embed(), view=MainMenuView(self.owner_id))
        elif action in {"add_table", "add_recipe", "edit_recipe", "remove_recipe", "resolve_report", "restore_history"}:
            await interaction.response.send_modal(AdminActionModal(action))
        elif action == "import_json":
            await interaction.response.send_modal(ImportRecipeModal())
        elif action == "analytics":
            await interaction.response.send_message(embed=analytics_embed(get_guild_recipe_data(interaction.guild_id), read_json(STATS_FILE, {})), ephemeral=True)
        elif action == "backup":
            path = create_backup()
            await interaction.response.send_message(f"Backup created: **{path.name}**", ephemeral=True)
        elif action == "download_backup":
            from crafting import BACKUP_DIR
            backups = sorted(BACKUP_DIR.glob("crafting-backup-*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
            if not backups:
                await interaction.response.send_message("No backup files are available yet. Create a backup first.", ephemeral=True)
                return
            latest = backups[0]
            await interaction.response.send_message(
                content="Download this backup and keep an external copy outside Discloud.",
                file=discord.File(latest, filename=latest.name),
                ephemeral=True,
            )
        elif action == "export":
            payload = json.dumps(get_guild_recipe_data(interaction.guild_id), ensure_ascii=False, indent=2).encode("utf-8")
            await interaction.response.send_message("Current recipe directory export:", file=discord.File(io.BytesIO(payload), filename="crafting-recipes-export.json"), ephemeral=True)
        elif action == "export_csv":
            payload = recipes_csv_bytes(get_guild_recipe_data(interaction.guild_id))
            await interaction.response.send_message("Complete ingredient occurrence export (duplicate entries are preserved):", file=discord.File(io.BytesIO(payload), filename="fivem-crafting-ingredients.csv"), ephemeral=True)
        elif action == "export_xlsx":
            payload = recipes_xlsx_bytes(get_guild_recipe_data(interaction.guild_id))
            await interaction.response.send_message("Excel workbook with all ingredient occurrences:", file=discord.File(io.BytesIO(payload), filename="fivem-crafting-directory.xlsx"), ephemeral=True)
        elif action == "validate":
            active_data = include_usable_item_recipes(get_guild_recipe_data(interaction.guild_id))
            findings = validate_recipe_data(active_data) + validate_city_reference_data(active_data)
            await interaction.response.send_message(embed=validation_embed(findings), ephemeral=True)
        elif action == "history":
            history = [item for item in read_json(HISTORY_FILE, []) if item.get("guild_id") == interaction.guild_id]
            if not history:
                await interaction.response.send_message("No recipe changes have been recorded yet. Future admin edits will appear here.", ephemeral=True)
                return
            embed = discord.Embed(title="🕘 Recipe Change History", description=f"Showing the latest {min(10, len(history))} change(s). Use Restore a previous version with an entry number to roll back.", color=COLOR)
            for item in reversed(history[-10:]):
                embed.add_field(name=f"#{item['id']} · {item.get('action', 'change')}", value=f"{item.get('summary', '')}\nBy user ID: {item.get('actor_id', 'unknown')}\n{item.get('created_at', 'unknown')}", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        elif action == "health":
            data = get_guild_recipe_data(interaction.guild_id)
            total = sum(len(t.get("recipes", [])) for t in data.get("tables", []))
            backups = list(BACKUP_DIR.glob("crafting-backup-*.json"))
            status = "Healthy" if bot.is_ready() and data.get("tables") else "Needs attention"
            embed = discord.Embed(title="🩺 Crafting Bot Health", description=f"**Status:** {status}\n**Bot connected:** {bot.is_ready()}\n**Tables:** {len(data.get('tables', []))}\n**Recipes:** {total}\n**Backups available:** {len(backups)}\n**Inventory file:** {'Present' if INVENTORIES_FILE.exists() else 'Not created'}\n**Reports file:** {'Present' if REPORTS_FILE.exists() else 'Not created'}", color=COLOR)
            embed.add_field(name="Storage note", value="Runtime files on Discloud may not survive host-side rebuilds. Download backups externally.", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        elif action == "audit":
            entries = [item for item in read_json(AUDIT_FILE, []) if item.get("guild_id") == interaction.guild_id][-10:]
            embed = discord.Embed(title="🧾 Activity Audit Log", color=COLOR)
            for item in reversed(entries):
                embed.add_field(name=f"{item.get('action')} · {item.get('created_at', '')[:19]}", value=f"By user ID: {item.get('actor_id')}\n{item.get('details', '')}", inline=False)
            if not entries:
                embed.description = "No tracked actions yet. Recipe changes and inventory restores will appear here."
            await interaction.response.send_message(embed=embed, ephemeral=True)
        elif action == "aliases":
            await interaction.response.send_modal(AliasManagerModal())
        elif action == "profile":
            await interaction.response.send_modal(ProfileCreateModal())
        elif action == "profile_switch":
            await interaction.response.send_modal(ProfileSelectModal())
        elif action == "stats":
            data = get_guild_recipe_data(interaction.guild_id)
            total = sum(len(t.get("recipes", [])) for t in data["tables"])
            lines = "\n".join(f"• {t['name']}: {len(t.get('recipes', []))} recipes" for t in data["tables"])
            embed = discord.Embed(title="📊 Crafting Directory Admin", description=lines or "No tables configured.", color=COLOR)
            embed.add_field(name="Tables", value=str(len(data["tables"])))
            embed.add_field(name="Recipes", value=str(total))
            embed.add_field(name="Runtime admin data", value="Active" if OVERRIDE_FILE.exists() else "Not created yet")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        elif action == "reports":
            reports = read_json(REPORTS_FILE, [])
            open_reports = [item for item in reports if item.get("status") == "open"][-10:]
            if not open_reports:
                await interaction.response.send_message("There are no open recipe reports.", ephemeral=True)
                return
            embed = discord.Embed(title="📨 Open Crafting Reports", color=COLOR)
            for report in reversed(open_reports[-5:]):
                context = " · ".join(x for x in [report.get("issue_type", ""), report.get("table", ""), report.get("recipe", "")] if x)
                embed.add_field(name=f"Report #{report['id']} · {context[:140]}", value=f"{report.get('details', '')[:350]}\nSubmitted: {report.get('created_at', 'unknown')}", inline=False)
            if len(open_reports) > 5:
                embed.set_footer(text=f"Showing 5 of {len(open_reports)} open reports. Resolve older reports by ID.")
            await interaction.response.send_message(embed=embed, ephemeral=True)


class RecipeCalculatorModal(SafeModal, title="Calculate recipe shopping list"):
    table = discord.ui.TextInput(label="Exact crafting table name", placeholder="Example: Glovebox Table", max_length=100)
    recipe = discord.ui.TextInput(label="Exact recipe name", placeholder="Example: Example Recipe", max_length=100)
    batches = discord.ui.TextInput(label="How many batches?", placeholder="1", default="1", max_length=3)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            batch_count = int(self.batches.value.strip())
            result = calculate_recipe_ingredients(include_usable_item_recipes(get_guild_recipe_data(interaction.guild_id)), self.table.value, self.recipe.value, batch_count)
        except (ValueError, TypeError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(embed=recipe_shopping_embed(result), ephemeral=True)


class IngredientDirectoryView(SafeView):
    def __init__(self, owner_id: int, data: dict):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.data = data
        self.page = 0
        self.page_size = 5
        self.page_count = max(1, (len(build_ingredient_directory(data)) + self.page_size - 1) // self.page_size)
        self.refresh_buttons()

    def refresh_buttons(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id == "ingredient_previous":
                child.disabled = self.page <= 0
            elif isinstance(child, discord.ui.Button) and child.custom_id == "ingredient_next":
                child.disabled = self.page >= self.page_count - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This private ingredient directory belongs to someone else.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, custom_id="ingredient_previous", row=0)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self.refresh_buttons()
        await interaction.response.edit_message(embed=ingredient_directory_embed(self.data, self.page, self.page_size), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, custom_id="ingredient_next", row=0)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.page_count - 1, self.page + 1)
        self.refresh_buttons()
        await interaction.response.edit_message(embed=ingredient_directory_embed(self.data, self.page, self.page_size), view=self)

    @discord.ui.button(label="Download full list", style=discord.ButtonStyle.success, emoji="📄", custom_id="ingredient_download", row=0)
    async def download_document(self, interaction: discord.Interaction, button: discord.ui.Button):
        payload = ingredient_directory_document(self.data).encode("utf-8")
        file = discord.File(io.BytesIO(payload), filename="fivem-all-ingredients-directory.txt")
        await interaction.response.send_message(
            content="Here is the complete ingredient directory.",
            file=file,
            ephemeral=True,
        )


def _saved_inventory_key(guild_id: int | None, user_id: int) -> tuple[str, str]:
    return (str(guild_id or "dm"), str(user_id))


def _load_saved_inventory(guild_id: int | None, user_id: int):
    guild_key, user_key = _saved_inventory_key(guild_id, user_id)
    all_data = read_json(INVENTORIES_FILE, {})
    return all_data.get(guild_key, {}).get(user_key, {"items": {}, "updated_at": None})


def _save_inventory_items(guild_id: int | None, user_id: int, items: dict[str, int]):
    guild_key, user_key = _saved_inventory_key(guild_id, user_id)
    with file_lock():
        all_data = read_json(INVENTORIES_FILE, {})
        guild_data = all_data.setdefault(guild_key, {})
        guild_data[user_key] = {"items": items, "updated_at": discord.utils.utcnow().isoformat()}
        write_json(INVENTORIES_FILE, all_data)


def _delete_saved_inventory(guild_id: int | None, user_id: int):
    guild_key, user_key = _saved_inventory_key(guild_id, user_id)
    with file_lock():
        all_data = read_json(INVENTORIES_FILE, {})
        guild_data = all_data.get(guild_key, {})
        guild_data.pop(user_key, None)
        if not guild_data:
            all_data.pop(guild_key, None)
        write_json(INVENTORIES_FILE, all_data)


def _shopping_lists_for(guild_id, user_id):
    all_data = read_json(SHOPPING_LISTS_FILE, {})
    return all_data.get(str(guild_id or "dm"), {}).get(str(user_id), [])


def _save_shopping_list(guild_id, user_id, name: str, items: dict[str, int]):
    with file_lock():
        all_data = read_json(SHOPPING_LISTS_FILE, {})
        guild_data = all_data.setdefault(str(guild_id or "dm"), {})
        lists = guild_data.setdefault(str(user_id), [])
        if len(lists) >= 20:
            raise ValueError("You can save up to 20 shopping lists. Delete an old list first.")
        saved = {
            "id": __import__("uuid").uuid4().hex[:10],
            "name": name[:60],
            "items": [{"name": item, "required": int(quantity), "collected": 0}
                      for item, quantity in sorted(items.items(), key=lambda pair: pair[0].casefold())],
            "created_at": discord.utils.utcnow().isoformat(),
            "updated_at": discord.utils.utcnow().isoformat(),
        }
        lists.append(saved)
        write_json(SHOPPING_LISTS_FILE, all_data)
        return saved


def _update_shopping_lists(guild_id, user_id, lists):
    with file_lock():
        all_data = read_json(SHOPPING_LISTS_FILE, {})
        guild_data = all_data.setdefault(str(guild_id or "dm"), {})
        guild_data[str(user_id)] = lists
        write_json(SHOPPING_LISTS_FILE, all_data)


def _shopping_list_embed(lists, selected_index):
    embed = discord.Embed(title="🛒 My Saved Shopping Lists", color=COLOR)
    if not lists:
        embed.description = "You have no saved shopping lists yet. Choose Create list to save ingredients and quantities."
        return embed
    selected_index = max(0, min(selected_index, len(lists) - 1))
    shopping_list = lists[selected_index]
    items = shopping_list.get("items", [])
    total = sum(int(item.get("required", 0)) for item in items)
    collected = sum(min(int(item.get("collected", 0)), int(item.get("required", 0))) for item in items)
    remaining = total - collected
    lines = []
    for item in items:
        required = int(item.get("required", 0))
        have = min(int(item.get("collected", 0)), required)
        marker = "☑️" if have >= required else "⬜"
        lines.append(f"{marker} **{item.get('name', 'Item')}** — {have:,}/{required:,} collected · {required-have:,} remaining")
    embed.description = (
        f"**List:** {shopping_list.get('name', 'Shopping list')} ({selected_index + 1}/{len(lists)})\n"
        f"**Progress:** {collected:,}/{total:,} collected · **{remaining:,} remaining**\n\n"
        + ("\n".join(lines) or "This list has no items.")
    )[:4000]
    embed.set_footer(text="Select an item, then use Mark collected / Undo to update its checklist.")
    return embed


class SavedShoppingListModal(SafeModal, title="Create a shopping list"):
    name = discord.ui.TextInput(label="List name", placeholder="Weekend supplies", max_length=60)
    items = discord.ui.TextInput(
        label="Required items and quantities",
        style=discord.TextStyle.paragraph,
        placeholder="Steel x20, Plastic x10, Rubber x5",
        max_length=1800,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            items = parse_inventory(self.items.value)
            if not items or len(items) > 25:
                raise ValueError("Enter between 1 and 25 different item names.")
            saved = _save_shopping_list(interaction.guild_id, interaction.user.id, self.name.value.strip(), items)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        record_player_activity(interaction.guild_id, interaction.user.id, "Created shopping list", saved["name"])
        record_audit_event(interaction.guild_id, interaction.user.id, "shopping_list_create", saved["name"])
        view = SavedShoppingListsView(interaction.user.id, interaction.guild_id, selected_id=saved["id"])
        await interaction.response.send_message(embed=view.current_embed(), view=view, ephemeral=True)


class SavedShoppingListsView(SafeView):
    def __init__(self, owner_id: int, guild_id: int | None, selected_id: str | None = None):
        super().__init__(timeout=300)
        self.owner_id, self.guild_id = owner_id, guild_id
        self.lists = _shopping_lists_for(guild_id, owner_id)
        self.selected_index = next((i for i, item in enumerate(self.lists) if item.get("id") == selected_id), 0)
        self.selected_item = 0
        self.list_select = discord.ui.Select(
            placeholder="Choose a saved shopping list",
            options=[discord.SelectOption(label=item.get("name", "Shopping list")[:100], value=str(i), default=i == self.selected_index)
                     for i, item in enumerate(self.lists[:25])] or
                    [discord.SelectOption(label="No saved lists yet", value="none")],
            disabled=not bool(self.lists),
            row=0,
        )
        self.list_select.callback = self.choose_list
        self.add_item(self.list_select)
        self.item_select = discord.ui.Select(
            placeholder="Choose an item to update",
            options=self._item_options(),
            disabled=not bool(self.lists and self.lists[self.selected_index].get("items")),
            row=1,
        )
        self.item_select.callback = self.choose_item
        self.add_item(self.item_select)

    def _item_options(self):
        if not self.lists:
            return [discord.SelectOption(label="No items available", value="none")]
        items = self.lists[self.selected_index].get("items", [])
        return [
            discord.SelectOption(
                label=f"{item.get('name', 'Item')} · {int(item.get('collected', 0))}/{int(item.get('required', 0))}"[:100],
                value=str(i),
                default=i == self.selected_item,
            )
            for i, item in enumerate(items[:25])
        ] or [discord.SelectOption(label="No items in this list", value="none")]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id or interaction.guild_id != self.guild_id:
            await interaction.response.send_message("This private shopping list belongs to someone else. Open your own from /crafting.", ephemeral=True)
            return False
        return True

    def current_embed(self):
        self.lists = _shopping_lists_for(self.guild_id, self.owner_id)
        return _shopping_list_embed(self.lists, self.selected_index)

    async def choose_list(self, interaction: discord.Interaction):
        self.selected_index = int(interaction.data["values"][0])
        self.selected_item = 0
        self.lists = _shopping_lists_for(self.guild_id, self.owner_id)
        self.item_select.options = self._item_options()
        self.item_select.disabled = not bool(self.lists and self.lists[self.selected_index].get("items"))
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    async def choose_item(self, interaction: discord.Interaction):
        self.selected_item = int(interaction.data["values"][0])
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    @discord.ui.button(label="Create list", emoji="➕", style=discord.ButtonStyle.success, row=2)
    async def create_list(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SavedShoppingListModal())

    @discord.ui.button(label="Mark collected / Undo", emoji="☑️", style=discord.ButtonStyle.primary, row=2)
    async def toggle_collected(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.lists = _shopping_lists_for(self.guild_id, self.owner_id)
        if not self.lists or not self.lists[self.selected_index].get("items"):
            await interaction.response.send_message("Create a list with at least one item first.", ephemeral=True)
            return
        item = self.lists[self.selected_index]["items"][self.selected_item]
        required = int(item.get("required", 0))
        item["collected"] = 0 if int(item.get("collected", 0)) >= required else required
        self.lists[self.selected_index]["updated_at"] = discord.utils.utcnow().isoformat()
        _update_shopping_lists(self.guild_id, self.owner_id, self.lists)
        record_player_activity(self.guild_id, self.owner_id, "Updated shopping checklist", item.get("name", "Item"))
        self.item_select.options = self._item_options()
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    @discord.ui.button(label="Delete list", emoji="🗑️", style=discord.ButtonStyle.danger, row=2)
    async def delete_list(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.lists = _shopping_lists_for(self.guild_id, self.owner_id)
        if not self.lists:
            await interaction.response.send_message("There is no saved list to delete.", ephemeral=True)
            return
        removed = self.lists.pop(self.selected_index)
        _update_shopping_lists(self.guild_id, self.owner_id, self.lists)
        self.selected_index = min(self.selected_index, max(0, len(self.lists) - 1))
        self.selected_item = 0
        self.list_select.options = [
            discord.SelectOption(label=item.get("name", "Shopping list")[:100], value=str(i), default=i == self.selected_index)
            for i, item in enumerate(self.lists[:25])
        ] or [discord.SelectOption(label="No saved lists yet", value="none")]
        self.list_select.disabled = not bool(self.lists)
        self.item_select.options = self._item_options()
        self.item_select.disabled = not bool(self.lists and self.lists[self.selected_index].get("items"))
        record_player_activity(self.guild_id, self.owner_id, "Deleted shopping list", removed.get("name", "Shopping list"))
        await interaction.response.edit_message(embed=self.current_embed(), view=self)


def _saved_inventory_embed(items: dict[str, int], updated_at: str | None = None):
    embed = discord.Embed(
        title="🧺 My Saved Inventory",
        description=f"**{len(items)} item name(s)** saved. Your stock is private to your Discord account in this server.",
        color=COLOR,
    )
    lines = [f"• **{name}** ×{quantity}" for name, quantity in sorted(items.items(), key=lambda pair: pair[0].casefold())]
    embed.add_field(name="Saved stock", value="\n".join(lines)[:3900] or "No items saved yet. Choose Update inventory to add your stock.", inline=False)
    if updated_at:
        embed.set_footer(text=f"Last updated: {updated_at[:19].replace('T', ' ')} UTC")
    return embed


class SaveInventoryModal(SafeModal, title="Update my saved inventory"):
    inventory = discord.ui.TextInput(
        label="Your current stock (replaces saved list)",
        style=discord.TextStyle.paragraph,
        placeholder="Clean Weed Bud x10, Cheesecloth x4",
        max_length=1800,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            items = parse_inventory(self.inventory.value)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        _save_inventory_items(interaction.guild_id, interaction.user.id, items)
        record_audit_event(interaction.guild_id, interaction.user.id, "inventory_update", f"Saved {len(items)} inventory item(s)")
        await interaction.response.send_message(
            embed=_saved_inventory_embed(items, discord.utils.utcnow().isoformat()),
            ephemeral=True,
        )


class CheckSavedInventoryModal(SafeModal, title="Plan using my saved inventory"):
    table = discord.ui.TextInput(label="Exact crafting table", max_length=100)
    recipe = discord.ui.TextInput(label="Exact recipe name", max_length=100)
    batches = discord.ui.TextInput(label="Target batches", default="1", max_length=3)

    async def on_submit(self, interaction: discord.Interaction):
        saved = _load_saved_inventory(interaction.guild_id, interaction.user.id)
        items = saved.get("items") or {}
        if not items:
            await interaction.response.send_message("You haven't saved any stock yet. Open My saved inventory and choose Update inventory first.", ephemeral=True)
            return
        inventory_text = ", ".join(f"{name} x{quantity}" for name, quantity in items.items())
        try:
            result = inventory_plan(include_usable_item_recipes(get_guild_recipe_data(interaction.guild_id)), self.table.value, self.recipe.value, int(self.batches.value.strip()), inventory_text)
        except (ValueError, TypeError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        embed = discord.Embed(
            title="🧮 Saved inventory plan: " + result["recipe"][:180],
            description=f"**Batches covered by recorded ingredients:** {result['available_batches']} / {result['target_batches']}\nCalculated from your saved stock; review any data notes below.",
            color=COLOR,
        )
        missing_lines = [f"• **{name}** ×{quantity}" for name, quantity in result["missing"].items()]
        required_lines = [f"• **{name}** ×{quantity}" for name, quantity in result["required"].items()]
        embed.add_field(name="Still missing", value="\n".join(missing_lines)[:1000] or "Nothing missing.", inline=False)
        embed.add_field(name="Required total", value="\n".join(required_lines)[:1000] or "None", inline=False)
        if result.get("notes"):
            embed.add_field(name="Data review notes", value="\n".join(f"• {note}" for note in result["notes"])[:1024], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ClearInventoryConfirmView(SafeView):
    def __init__(self, owner_id: int, guild_id: int | None):
        super().__init__(timeout=60)
        self.owner_id, self.guild_id = owner_id, guild_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id or interaction.guild_id != self.guild_id:
            await interaction.response.send_message("This inventory confirmation belongs to someone else.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Yes, clear my saved inventory", style=discord.ButtonStyle.danger)
    async def confirm_clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        _delete_saved_inventory(self.guild_id, self.owner_id)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Your saved inventory has been cleared.", embed=None, view=self)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Nothing was changed.", embed=None, view=self)


class ShareShoppingListView(SafeView):
    def __init__(self, owner_id, embed):
        super().__init__(timeout=120)
        self.owner_id, self.embed = owner_id, embed

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Only the person who created this list can share it.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Share this list in the channel", style=discord.ButtonStyle.primary, emoji="📨")
    async def share(self, interaction, button):
        await interaction.response.send_message(embed=self.embed)
        button.disabled = True
        await interaction.edit_original_response(view=self)


class RestoreInventoryModal(SafeModal, title="Restore saved inventory"):
    backup_json = discord.ui.TextInput(label="Paste your exported inventory JSON", style=discord.TextStyle.paragraph, max_length=1800)

    async def on_submit(self, interaction):
        try:
            payload = json.loads(self.backup_json.value)
            if payload.get("version") != 1 or not isinstance(payload.get("items"), dict):
                raise ValueError("Unsupported inventory backup format.")
            items = {}
            for name, quantity in payload["items"].items():
                name = str(name).strip()
                quantity = int(quantity)
                if not name or quantity < 0 or quantity > 1000000:
                    raise ValueError("Inventory items need names and quantities from 0 to 1,000,000.")
                if quantity:
                    items[name] = quantity
            if len(items) > 100:
                raise ValueError("A saved inventory can contain at most 100 item names.")
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            await interaction.response.send_message(f"Could not restore that backup: {exc}", ephemeral=True)
            return
        _save_inventory_items(interaction.guild_id, interaction.user.id, items)
        record_audit_event(interaction.guild_id, interaction.user.id, "inventory_restore", f"Restored {len(items)} inventory item(s)")
        await interaction.response.send_message(embed=_saved_inventory_embed(items, discord.utils.utcnow().isoformat()), ephemeral=True)


class InventoryTrackerView(SafeView):
    def __init__(self, owner_id: int, guild_id: int | None):
        super().__init__(timeout=300)
        self.owner_id, self.guild_id = owner_id, guild_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id or interaction.guild_id != self.guild_id:
            await interaction.response.send_message("This private inventory menu belongs to someone else. Open your own with /dashboard.", ephemeral=True)
            return False
        return True

    def current_embed(self):
        saved = _load_saved_inventory(self.guild_id, self.owner_id)
        return _saved_inventory_embed(saved.get("items") or {}, saved.get("updated_at"))

    @discord.ui.button(label="Update inventory", style=discord.ButtonStyle.success, emoji="➕", row=0)
    async def update_inventory(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SaveInventoryModal())

    @discord.ui.button(label="Refresh / view", style=discord.ButtonStyle.secondary, emoji="🔄", row=0)
    async def refresh_inventory(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    @discord.ui.button(label="Plan a recipe", style=discord.ButtonStyle.primary, emoji="🧮", row=1)
    async def plan_recipe(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CheckSavedInventoryModal())

    @discord.ui.button(label="Clear inventory", style=discord.ButtonStyle.danger, emoji="🗑️", row=1)
    async def clear_inventory(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Are you sure you want to clear your saved stock?",
            view=ClearInventoryConfirmView(self.owner_id, self.guild_id),
            ephemeral=True,
        )

    @discord.ui.button(label="Export backup", style=discord.ButtonStyle.secondary, emoji="📤", row=2)
    async def export_inventory(self, interaction, button):
        saved = _load_saved_inventory(self.guild_id, self.owner_id)
        payload = json.dumps({"version": 1, "items": saved.get("items") or {}, "updated_at": saved.get("updated_at")}, ensure_ascii=False, indent=2).encode("utf-8")
        await interaction.response.send_message("Keep this file somewhere safe. Use Restore backup to import it later.", file=discord.File(io.BytesIO(payload), filename="my-fivem-inventory.json"), ephemeral=True)

    @discord.ui.button(label="Restore backup", style=discord.ButtonStyle.secondary, emoji="📥", row=2)
    async def restore_inventory(self, interaction, button):
        await interaction.response.send_modal(RestoreInventoryModal())


class ChatRecipeMatchView(SafeView):
    def __init__(self, owner_id: int, query: str, matches: list[dict]):
        super().__init__(timeout=180)
        self.owner_id, self.query, self.matches = owner_id, query, matches
        options = [
            discord.SelectOption(
                label=f"{match['recipe']} • {match['table']}"[:100],
                value=str(index),
                description=match.get("match_label", "Recipe match")[:100],
            )
            for index, match in enumerate(matches[:3])
        ]
        select = discord.ui.Select(placeholder="Choose the closest recipe match", options=options)
        select.callback = self.choose_match
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Only the person who asked for this lookup can choose its result.", ephemeral=True)
            return False
        return True

    async def choose_match(self, interaction: discord.Interaction):
        index = int(interaction.data["values"][0])
        match = self.matches[index]
        ingredient_lines = [f"• **{name}** ×{quantity}" for name, quantity in match.get("ingredients", [])]
        description = f"**Table:** {match['table']}\n**Recipe:** {match['recipe']}\n**Ingredients:**\n" + ("\n".join(ingredient_lines) if ingredient_lines else "None recorded")
        if match.get("tools"):
            description += "\n**Tools (not consumed):** " + ", ".join(match["tools"])
        if match.get("notes"):
            description += "\n\n**Data review notes:**\n" + "\n".join(f"• {note}" for note in match["notes"])
        embed = discord.Embed(
            title=f"Crafting match: {match['recipe'][:180]}",
            description=description[:4000],
            color=COLOR,
        )
        embed.set_footer(text="Selected from the server's saved FiveM recipe directory • Use /dashboard for more")
        await interaction.response.edit_message(embed=embed, view=self)


class MainMenuView(SafeView):
    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        options = [
            discord.SelectOption(label="Browse recipes", value="browse", description="Choose a table and recipe", emoji="📚"),
            discord.SelectOption(label="Search recipes", value="search", description="Search names, ingredients, tools, or tables", emoji="🔎"),
            discord.SelectOption(label="Find ingredient across tables", value="ingredient_lookup", description="See every table and recipe that uses an exact ingredient", emoji="🧩"),
            discord.SelectOption(label="All ingredients", value="all_ingredients", description="Browse or download the complete ingredient list", emoji="📋"),
            discord.SelectOption(label="Recipe shopping list", value="shopping_list", description="Calculate ingredients for a chosen batch count", emoji="🧮"),
            discord.SelectOption(label="Crafting table comparison", value="compare_tables", description="See shared and table-exclusive ingredients", emoji="⚖️"),
            discord.SelectOption(label="Production chains", value="dependency", description="Trace outputs to base ingredients", emoji="🔗"),
            discord.SelectOption(label="Full production cost planner", value="production_cost", description="Multiply nested crafting steps into total base ingredients", emoji="🧮"),
            discord.SelectOption(label="Inventory calculator", value="inventory", description="Calculate batches from stock entered once", emoji="🎒"),
            discord.SelectOption(label="My saved inventory", value="inventory_tracker", description="Save your personal stock and reuse it for recipe plans", emoji="🧺"),
            discord.SelectOption(label="My saved shopping lists", value="shopping_lists", description="Save ingredient checklists and track what you have collected", emoji="🛒"),
            discord.SelectOption(label="My recent activity", value="recent_activity", description="Review your latest searches and planning actions", emoji="🕘"),
            discord.SelectOption(label="Multi-recipe planner", value="multi_plan", description="Combine several recipes into one list", emoji="🧾"),
            discord.SelectOption(label="Advanced search", value="advanced_search", description="Filter recipes by multiple criteria", emoji="🧰"),
            discord.SelectOption(label="Item database", value="item_page", description="Open an item's production and usage page", emoji="📖"),
            discord.SelectOption(label="Recipe comparison", value="recipe_compare", description="Compare two recipes", emoji="⚖️"),
            discord.SelectOption(label="Help and instructions", value="help", description="How to use the crafting directory", emoji="📘"),
            discord.SelectOption(label="Report a recipe issue", value="report", description="Privately report missing or incorrect data", emoji="📨"),
        ]
        options.append(discord.SelectOption(label="Admin tools", value="admin", description="Manage recipes, backups, exports, and reports", emoji="⚙️"))
        select = discord.ui.Select(placeholder="What would you like to do?", options=options)
        select.callback = self.choose_action
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This private menu belongs to someone else. Run /dashboard to open your own.", ephemeral=True)
            return False
        return True

    async def choose_action(self, interaction: discord.Interaction):
        action = interaction.data["values"][0]
        record_player_activity(interaction.guild_id, interaction.user.id, "Opened crafting tool", action.replace("_", " ").title())
        if action == "browse":
            view = CraftingDirectoryView(
                self.owner_id,
                include_usable_item_recipes(get_guild_recipe_data(interaction.guild_id)),
                on_table_selected=record_table_usage,
                on_home=return_to_dashboard,
            )
            await interaction.response.edit_message(embed=view.current_embed(), view=view)
        elif action == "search":
            await interaction.response.send_modal(SearchModal())
        elif action == "ingredient_lookup":
            await interaction.response.send_modal(IngredientLookupModal())
        elif action == "all_ingredients":
            view = IngredientDirectoryView(self.owner_id, include_usable_item_recipes(get_guild_recipe_data(interaction.guild_id)))
            await interaction.response.edit_message(
                embed=ingredient_directory_embed(include_usable_item_recipes(get_guild_recipe_data(interaction.guild_id)), 0, view.page_size),
                view=view,
            )
        elif action == "shopping_list":
            await interaction.response.send_modal(RecipeCalculatorModal())
        elif action == "compare_tables":
            await interaction.response.edit_message(embed=table_comparison_embed(include_usable_item_recipes(get_guild_recipe_data(interaction.guild_id))), view=self)
        elif action == "dependency":
            await interaction.response.send_modal(DependencyModal())
        elif action == "production_cost":
            await interaction.response.send_modal(ProductionCostModal())
        elif action == "inventory":
            await interaction.response.send_modal(InventoryModal())
        elif action == "inventory_tracker":
            view = InventoryTrackerView(self.owner_id, interaction.guild_id)
            await interaction.response.edit_message(embed=view.current_embed(), view=view)
        elif action == "shopping_lists":
            view = SavedShoppingListsView(self.owner_id, interaction.guild_id)
            await interaction.response.edit_message(embed=view.current_embed(), view=view)
        elif action == "recent_activity":
            source_embed = recent_activity_embed(interaction.guild_id, self.owner_id)
            pager = InformationPagerView(self.owner_id, source_embed, 5)
            await interaction.response.edit_message(embed=pager.current_embed(), view=pager)
        elif action == "multi_plan":
            await interaction.response.send_modal(MultiRecipeModal())
        elif action == "advanced_search":
            await interaction.response.send_modal(AdvancedSearchModal())
        elif action == "item_page":
            await interaction.response.send_modal(ItemPageModal())
        elif action == "recipe_compare":
            await interaction.response.send_modal(RecipeCompareModal())
        elif action == "help":
            await interaction.response.edit_message(embed=help_embed(), view=self)
        elif action == "report":
            await interaction.response.send_modal(ReportModal())
        elif action == "admin":
            embed = discord.Embed(title="⚙️ Fjord Cartel • Management Tools", description="Choose an action below. Changes automatically create a backup before saving.", color=COLOR)
            await interaction.response.edit_message(embed=embed, view=AdminMenuView(self.owner_id))



class DependencyModal(SafeModal, title="Trace a production chain"):
    item = discord.ui.TextInput(label="Item / recipe output name", max_length=100)
    async def on_submit(self, interaction):
        lines = dependency_lines(dependency_chain(include_usable_item_recipes(get_guild_recipe_data(interaction.guild_id)), self.item.value.strip()))
        embed = discord.Embed(title="Production chain: " + self.item.value.strip()[:180], description="\n".join(lines)[:3900], color=COLOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ProductionCostModal(SafeModal, title="Full production requirements"):
    table = discord.ui.TextInput(label="Exact crafting table", max_length=100)
    recipe = discord.ui.TextInput(label="Exact recipe name", max_length=100)
    batches = discord.ui.TextInput(label="Final batches to produce", default="1", max_length=3)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            result = expanded_production_requirements(
                include_usable_item_recipes(get_guild_recipe_data(interaction.guild_id)), self.table.value, self.recipe.value, int(self.batches.value.strip())
            )
        except (ValueError, TypeError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        embed = discord.Embed(
            title=f"🧮 Full production requirements: {result['recipe'][:170]}",
            description=f"**Starting table:** {result['table']}\n**Final batches:** {result['batches']}\nNested recipes are multiplied automatically when an item has exactly one recorded producer.",
            color=COLOR,
        )
        ingredients = [f"• **{name}** ×{quantity}" for name, quantity in result["base_ingredients"].items()]
        embed.add_field(name="Total base ingredients to gather", value="\n".join(ingredients)[:1000] or "No base ingredients recorded.", inline=False)
        steps = [f"• {item['recipe']} — {item['table']} ×{item['batches']} batch(es)" for item in result["expanded_recipes"]]
        embed.add_field(name="Production steps", value="\n".join(steps[:12])[:1000] or "No production steps.", inline=False)
        if result["tools"]:
            embed.add_field(name="Tools (not consumed)", value=", ".join(result["tools"])[:1000], inline=False)
        if result["notes"]:
            embed.add_field(name="Data review / manual choice notes", value="\n".join(result["notes"][:4])[:1000], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class InventoryModal(SafeModal, title="Inventory calculator"):
    table = discord.ui.TextInput(label="Exact crafting table", max_length=100)
    recipe = discord.ui.TextInput(label="Exact recipe name", max_length=100)
    batches = discord.ui.TextInput(label="Target batches", default="1", max_length=3)
    inventory = discord.ui.TextInput(label="Current stock: Item x5, Item x10", style=discord.TextStyle.paragraph, max_length=1500)
    async def on_submit(self, interaction):
        try:
            result = inventory_plan(include_usable_item_recipes(get_guild_recipe_data(interaction.guild_id)), self.table.value, self.recipe.value, int(self.batches.value.strip()), self.inventory.value)
        except (ValueError, TypeError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        embed = discord.Embed(title="Inventory plan: " + self.recipe.value, description="Craftable batches: " + str(result["available_batches"]) + " / " + str(result["target_batches"]), color=COLOR)
        missing_lines = [str(n) + " x" + str(q) for n,q in result["missing"].items()]
        required_lines = [str(n) + " x" + str(q) for n,q in result["required"].items()]
        embed.add_field(name="Missing for target", value="\n".join(missing_lines[:12])[:900] or "Nothing missing.", inline=False)
        embed.add_field(name="Required total", value="\n".join(required_lines[:12])[:900] or "None", inline=False)
        full_text = "INVENTORY PLAN\nRecipe: " + result["recipe"] + "\nTarget batches: " + str(result["target_batches"]) + "\nCraftable batches from stock: " + str(result["available_batches"]) + "\n\nMissing for target:\n" + ("\n".join(missing_lines) or "Nothing missing.") + "\n\nRequired total:\n" + "\n".join(required_lines)
        file = discord.File(io.BytesIO(full_text.encode("utf-8")), filename="fivem-inventory-plan.txt")
        await interaction.response.send_message(content="The complete inventory calculation is attached.", embed=embed, file=file, ephemeral=True)


class MultiRecipeModal(SafeModal, title="Multi-recipe planner"):
    requests = discord.ui.TextInput(label="One per line: Table | Recipe | batches", style=discord.TextStyle.paragraph, max_length=1800)
    async def on_submit(self, interaction):
        try:
            parsed = []
            for line in self.requests.value.splitlines():
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) != 3:
                    raise ValueError("Use: Table | Recipe | batches")
                parsed.append((parts[0], parts[1], int(parts[2])))
            result = multi_recipe_plan(include_usable_item_recipes(get_guild_recipe_data(interaction.guild_id)), parsed)
        except (ValueError, TypeError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        embed = discord.Embed(title="Combined production plan", description="\n".join(result["selected"][:8])[:900], color=COLOR)
        ingredient_lines = ["- " + str(n) + " x" + str(q) for n,q in result["ingredients"].items()]
        embed.add_field(name="Combined ingredient totals", value="\n".join(ingredient_lines[:12])[:900] or "None", inline=False)
        if result["tools"]:
            embed.add_field(name="Tools (not consumed)", value=", ".join(result["tools"])[:700], inline=False)
        if result.get("notes"):
            embed.add_field(name="Data review notes", value="\n".join(f"• {note}" for note in result["notes"])[:1024], inline=False)
        full_text = "COMBINED PRODUCTION PLAN\n\nRecipes:\n" + "\n".join(result["selected"]) + "\n\nIngredients:\n" + "\n".join(ingredient_lines) + "\n\nTools (not consumed):\n" + ", ".join(result["tools"]) + "\n\nData review notes:\n" + "\n".join(result.get("notes", []))
        file = discord.File(io.BytesIO(full_text.encode("utf-8")), filename="fivem-combined-production-plan.txt")
        await interaction.response.send_message(content="The full combined plan is attached so no ingredient totals are cut off.", embed=embed, file=file, ephemeral=True)


class AdvancedSearchModal(SafeModal, title="Advanced search"):
    keyword = discord.ui.TextInput(label="Keyword (optional)", required=False, max_length=100)
    table = discord.ui.TextInput(label="Table contains (optional)", required=False, max_length=100)
    ingredient = discord.ui.TextInput(label="Ingredient contains (optional)", required=False, max_length=100)
    tool = discord.ui.TextInput(label="Tool contains (optional)", required=False, max_length=100)
    minimum = discord.ui.TextInput(label="Minimum ingredient rows", default="0", max_length=3)
    async def on_submit(self, interaction):
        try:
            results = advanced_search(include_usable_item_recipes(get_guild_recipe_data(interaction.guild_id)), self.keyword.value.strip(), self.table.value.strip(), self.ingredient.value.strip(), self.tool.value.strip(), int(self.minimum.value.strip()))
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        embed = discord.Embed(title="Advanced search results", description="Found " + str(len(results)) + " recipe(s).", color=COLOR)
        for table, recipe in results[:5]:
            summary = ", ".join(str(n) + " x" + str(q) for n,q in recipe.get("ingredients", []))
            if recipe.get("notes"):
                summary += "\nData review: " + " ".join(recipe["notes"])
            embed.add_field(name=(recipe.get("name", "Unnamed") + " - " + table)[:256], value=summary[:900] or "No ingredients", inline=False)
        if len(results) > 5:
            embed.set_footer(text=f"Showing 5 of {len(results)} results. Narrow the filters to see fewer matches.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ItemPageModal(SafeModal, title="Item database page"):
    item = discord.ui.TextInput(label="Exact item / ingredient name", max_length=100)
    async def on_submit(self, interaction):
        await interaction.response.send_message(embed=ingredient_usage_embed(include_usable_item_recipes(get_guild_recipe_data(interaction.guild_id)), self.item.value.strip()), ephemeral=True)


class RecipeCompareModal(SafeModal, title="Compare two recipes"):
    table_a = discord.ui.TextInput(label="First crafting table", max_length=100)
    recipe_a = discord.ui.TextInput(label="First recipe", max_length=100)
    table_b = discord.ui.TextInput(label="Second crafting table", max_length=100)
    recipe_b = discord.ui.TextInput(label="Second recipe", max_length=100)
    async def on_submit(self, interaction):
        try:
            result = recipe_comparison(include_usable_item_recipes(get_guild_recipe_data(interaction.guild_id)), self.table_a.value, self.recipe_a.value, self.table_b.value, self.recipe_b.value)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        embed = discord.Embed(title="Recipe comparison", description="A: " + result["a"]["recipe"] + " / " + result["a"]["table"] + "\nB: " + result["b"]["recipe"] + " / " + result["b"]["table"], color=COLOR)
        embed.add_field(name="Shared ingredients", value=", ".join(result["shared"]) or "None", inline=False)
        embed.add_field(name="Only in A", value=", ".join(result["only_a"]) or "None", inline=False)
        embed.add_field(name="Only in B", value=", ".join(result["only_b"]) or "None", inline=False)
        for label, recipe_result in (("A", result["a"]), ("B", result["b"])):
            if recipe_result.get("notes"):
                embed.add_field(name=f"Data review notes — {label}", value="\n".join(f"• {note}" for note in recipe_result["notes"])[:1024], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)



class ImportRecipeModal(SafeModal, title="Import / merge recipe JSON"):
    json_text = discord.ui.TextInput(label="Paste JSON with a top-level tables list", style=discord.TextStyle.paragraph, max_length=4000)
    mode = discord.ui.TextInput(label="Name conflicts: skip or replace", default="skip", max_length=10)
    async def on_submit(self, interaction):
        try:
            incoming = json.loads(self.json_text.value)
            mode = self.mode.value.strip().casefold()
            if mode not in {"skip", "replace"}:
                raise ValueError("Conflict mode must be skip or replace.")
            current = ensure_stable_ids(get_guild_recipe_data(interaction.guild_id))
            base_fingerprint = recipe_fingerprint(current)
            merged, summary = merge_recipe_import(current, incoming, mode)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            await interaction.response.send_message("Import rejected: " + str(exc), ephemeral=True)
            return
        description = "Tables added: " + str(summary["tables_added"]) + "\nRecipes added: " + str(summary["recipes_added"]) + "\nConflicts skipped: " + str(summary["skipped"]) + "\nReplaced: " + str(summary["replaced"]) + "\nValidation warnings: " + str(summary["warnings"]) + "\n\nNothing changed yet. Confirm to apply."
        embed = discord.Embed(title="Import preview", description=description, color=COLOR)
        await interaction.response.send_message(embed=embed, view=ImportConfirmView(interaction.user.id, merged, summary, base_fingerprint), ephemeral=True)


class ImportConfirmView(SafeView):
    def __init__(self, owner_id, merged, summary, base_fingerprint):
        super().__init__(timeout=120)
        self.owner_id, self.merged, self.summary = owner_id, merged, summary
        self.base_fingerprint = base_fingerprint
    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Only the member who started this import can confirm it.", ephemeral=True)
            return False
        return True
    @discord.ui.button(label="Confirm import", style=discord.ButtonStyle.success)
    async def confirm(self, interaction, button):
        current = ensure_stable_ids(get_guild_recipe_data(interaction.guild_id))
        if recipe_fingerprint(current) != self.base_fingerprint:
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(content="The recipe data changed after this preview was created. Nothing was imported. Reopen the import tool and create a fresh preview.", embed=None, view=self)
            return
        record_recipe_change(current, "import_merge", interaction.user.id, "Imported " + str(self.summary["recipes_added"]) + " recipes", interaction.guild_id)
        save_guild_recipe_data(interaction.guild_id, ensure_stable_ids(self.merged))
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Import applied. A backup and reversible history snapshot were created.", embed=None, view=self)
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Import cancelled. No recipe data was changed.", embed=None, view=self)


@bot.event
async def on_message(message: discord.Message):
    """Answer typo-tolerant chat lookups using only the saved FiveM recipe directory."""
    if message.author.bot:
        return
    # The bang prefix is reserved exclusively for natural-language questions.
    # All bot features and utilities are registered as Discord slash commands.
    if message.guild is None:
        return
    content = (message.content or "").strip()
    if not content.startswith("!"):
        return
    query = content[1:].strip()
    if query:
        record_player_activity(message.guild.id, message.author.id, "Asked a question", query[:120])
    if not query:
        await message.reply("Use ! only when asking a question, for example: !where can I buy ammonia?", mention_author=False)
        return
    if query.casefold() in {"help", "crafting"}:
        await message.reply("Use /crafting or /dashboard to open the bot menus. The ! prefix is reserved for questions.", mention_author=False)
        return
    weed_result = calculate_weed_growing_requirements(query)
    if weed_result is not None:
        if weed_result.get("error"):
            await message.reply(weed_result["error"], mention_author=False)
            return
        lowered = query.casefold()
        if any(term in lowered for term in ("system 1", "system one", "smoke on the water", "smoke on water")):
            selected = [("smoke", weed_result["systems"]["smoke"])]
        elif any(term in lowered for term in ("system 2", "system two", "grapeseed", "grape seed")):
            selected = [("grape", weed_result["systems"]["grape"])]
        else:
            selected = [("smoke", weed_result["systems"]["smoke"]), ("grape", weed_result["systems"]["grape"])]
        embed = discord.Embed(
            title="🌱 Weed Growing Calculator",
            description=(
                f"**Plants:** {weed_result['plants']:,}\n"
                f"**Planting in grass:** {'Yes — no Flower Pots needed' if weed_result['grass'] else 'No — Flower Pots included'}"
            ),
            color=COLOR,
        )
        for key, system in selected:
            lines = []
            for item, quantity in system["items"].items():
                lines.append(f"• **{item}:** {quantity:,} — $" + f"{system['costs'][item]:,}")
            location_lines = []
            for location, items in system["locations"].items():
                location_lines.append(f"**{location}:** {', '.join(items)}")
            embed.add_field(
                name=system["name"] + " — $" + f"{system['total']:,}",
                value="\n".join(lines) + "\n\n**Where to buy**\n" + "\n".join(location_lines),
                inline=False,
            )
            embed.add_field(name=system["name"] + " instructions", value=system["note"], inline=False)
        if len(selected) == 2:
            embed.set_footer(text="Mention System 1 / Smoke On The Water or System 2 / Grapeseed to show just one.")
        else:
            embed.set_footer(text="Water and reusable tools are counted as one purchase each; Flower Pots are omitted for grass planting.")
        await message.reply(embed=embed, mention_author=False)
        return


    raw_cocaine_result = calculate_raw_cocaine_requirements(query)
    if raw_cocaine_result is not None:
        if raw_cocaine_result.get("error"):
            await message.reply(raw_cocaine_result["error"], mention_author=False)
            return
        result = raw_cocaine_result
        embed = discord.Embed(
            title="🧮 Raw Cocaine Production Calculator",
            description=(
                f"**Target:** {result['target']:,} Raw Cocaine\n"
                f"**Picks required:** {result['picks']:,}\n"
                f"**Estimated output:** ~{result['estimated_output']:,} Raw Cocaine"
            ),
            color=COLOR,
        )
        material_lines = [f"• **{name}:** {quantity:,}" for name, quantity in result["materials"].items()]
        embed.add_field(name="Materials to collect", value="\n".join(material_lines), inline=False)
        embed.add_field(
            name="Cost",
            value="**$0 total** — Cement, Hydrochloric Acid, and Gasoline are free pickups.",
            inline=False,
        )
        if result["estimated_output"] > result["target"]:
            embed.add_field(
                name="Note",
                value=f"Each pick produces approximately 800, so you'll have about {result['estimated_output'] - result['target']:,} extra.",
                inline=False,
            )
        embed.set_footer(text="FJORD CARTEL • Raw Cocaine production estimate")
        await message.reply(embed=embed, mention_author=False)
        return

    price_result = calculate_shop_price_query(query)
    if price_result is not None:
        if price_result.get("error"):
            await message.reply(price_result["error"], mention_author=False)
            return
        has_quantity = price_result["quantity"] is not None
        embed = discord.Embed(
            title="🧮 Shop & Price Lookup" if not has_quantity else "🧮 Shop Price Calculator",
            color=COLOR,
        )
        embed.add_field(name="Item", value=price_result["item"], inline=True)
        embed.add_field(name="Where to buy", value=price_result["shop"], inline=True)
        embed.add_field(name="Price per item", value=f"${price_result['unit_price']:,}", inline=True)
        if has_quantity:
            embed.add_field(name="Quantity", value=f"{price_result['quantity']:,}", inline=True)
            embed.add_field(name="Total cost", value=f"**${price_result['total']:,}**", inline=True)
        embed.set_footer(text="FJORD CARTEL • Shop & location directory")
        await message.reply(embed=embed, mention_author=False)
        return

    if bot.recipe_data is None:
        await message.reply("The crafting directory is still loading. Try again shortly.", mention_author=False)
        return

    data = get_guild_recipe_data(message.guild.id)
    query_data = include_usable_item_recipes(data)
    lowered = query.casefold()

    # Postal/location questions search the same saved directory shown by /locations.
    postal_match = re.search(r"\b(\d{3,5})\b", query)
    asks_location = postal_match and any(word in lowered for word in ("where", "what", "postal", "location", "at "))
    if asks_location:
        postal = postal_match.group(1)
        directory = locations_embed()
        found = []
        for field in directory.fields:
            combined = f"{field.name}\n{field.value}"
            if re.search(r"(?<!\d)" + re.escape(postal) + r"(?!\d)", combined):
                found.append(field)
        if found:
            embed = discord.Embed(title=f"📍 Saved location: Postal {postal}", color=COLOR)
            for field in found[:8]:
                embed.add_field(name=field.name[:256], value=field.value[:1024], inline=False)
            embed.set_footer(text="FJORD CARTEL • Saved location directory")
            await message.reply(embed=embed, mention_author=False)
            return
        record_usage("no_result", query)
        await message.reply(f"I couldn't find Postal **{postal}** in the saved location directory. I won't guess its location.", mention_author=False)
        return

    # Questions about where an ingredient is used / what recipes use it.
    usage_markers = ("what uses", "what recipes use", "which recipes use", "where do i use", "used in", "used for", "what does")
    asks_usage = any(marker in lowered for marker in usage_markers) or (
        any(marker in lowered for marker in ("where is", "where's"))
        and any(word in lowered for word in ("used", "use", "made", "recipe", "does"))
    )
    if asks_usage:
        ingredient_query = query
        for phrase in ("where is ", "where's ", "what is ", "what's ", "what uses ", "what recipes use ", "which recipes use ", "where do i use ", "what does "):
            ingredient_query = re.sub(r"^" + re.escape(phrase), "", ingredient_query, flags=re.IGNORECASE)
        ingredient_query = re.sub(r"\b(used in|used for|used|use|made|at|the|for|do)\b", " ", ingredient_query, flags=re.IGNORECASE).strip(" ?.! ")
        if ingredient_query:
            embed = ingredient_usage_embed(query_data, ingredient_query)
            if embed.description and "No exact ingredient or tool-name matches" not in embed.description:
                await message.reply(embed=embed, mention_author=False)
                return
            # Try a typo-tolerant ingredient match, but label it as a suggestion.
            suggestions = chat_recipe_search(query_data, ingredient_query, limit=3)
            if suggestions and any(item.get("match_label","").startswith("Closest ingredient") for item in suggestions):
                lines = [f"• **{item['ingredients'][0][0]}** — {item['recipe']} ({item['table']})" for item in suggestions]
                await message.reply("I couldn't find that exact ingredient. Closest saved ingredient matches:\n" + "\n".join(lines), mention_author=False)
                return

    # Search the same saved shops, locations, usable items and help pages shown by slash commands.
    if any(term in lowered for term in ("where", "find", "sell", "location", "what is", "what does", "how do i use", "how to use", "how do i do", "how to do", "how do i start", "how to start", "how do i collect", "how to collect", "how do i get to", "tell me about", "what do i do")):
        info_matches = saved_information_matches(query)
        if info_matches:
            embed = discord.Embed(title="📚 Saved Fjord Cartel Information", color=COLOR)
            for item in info_matches[:6]:
                embed.add_field(name=f"{item['source']} · {item['title']}"[:256], value=item["value"][:1024] or "No details recorded.", inline=False)
            embed.set_footer(text="Answers are taken from the saved Shops, Locations, Usable Items and Commands pages.")
            await message.reply(embed=embed, mention_author=False)
            return

    # Estimate a recipe's batch count from the inventory the member supplies.
    inventory_query = re.search(r"\bwith\s*:?\s*(.+)$", query, re.IGNORECASE)
    if inventory_query and any(term in lowered for term in ("how many", "how much", "can i make", "can i craft", "can i produce")):
        target_query = query[:inventory_query.start()].strip()
        try:
            limited_result = calculate_inventory_limited_batches(query_data, target_query, inventory_query.group(1))
        except ValueError as exc:
            await message.reply(f"Inventory format error: {exc}", mention_author=False)
            return
        if limited_result is not None:
            if limited_result.get("error"):
                await message.reply(limited_result["error"], mention_author=False)
                return
            embed = discord.Embed(
                title="🧮 Inventory-Limited Recipe Calculator",
                description=(
                    f"**Recipe:** {limited_result['recipe']}\n"
                    f"**Table:** {limited_result['table']}\n"
                    f"**Maximum batches from the stock you listed:** {limited_result['batches']:,}"
                ),
                color=COLOR,
            )
            if limited_result["stock_used"]:
                embed.add_field(
                    name="Your listed stock",
                    value="\n".join(f"• **{name}:** {quantity:,}" for name, quantity in limited_result["stock_used"].items()),
                    inline=False,
                )
            if limited_result["missing"]:
                embed.add_field(
                    name="Other ingredients still needed",
                    value="\n".join(f"• **{name}:** {quantity:,}" for name, quantity in limited_result["missing"].items())[:1024],
                    inline=False,
                )
            if limited_result["tools"]:
                embed.add_field(name="Tools (not consumed)", value=", ".join(limited_result["tools"]), inline=False)
            if limited_result.get("notes"):
                embed.add_field(name="Data review notes", value="\n".join(f"• {note}" for note in limited_result["notes"])[:1024], inline=False)
            embed.set_footer(text="The batch limit uses only the stock you listed; missing ingredients are shown separately.")
            await message.reply(embed=embed, mention_author=False)
            return

    # Generic batch shopping list: !what do I need for 10 [recipe]?
    batch_match = re.search(r"\b(\d[\d,]*)\s*(?:x\s*)?(?:batches?\s+(?:of\s+)?)?(.+)$", query, re.IGNORECASE)
    asks_requirements = any(word in lowered for word in ("what do i need", "ingredients for", "shopping list for", "materials for", "how many ingredients", "make "))
    if batch_match and asks_requirements and any(word in lowered for word in ("need", "ingredients", "shopping", "materials", "make")):
        batch_count = int(batch_match.group(1).replace(",", ""))
        target_text = batch_match.group(2).strip(" ?.! ")
        if 1 <= batch_count <= 100000 and target_text:
            matches = chat_recipe_search(query_data, target_text, limit=4)
            exact = [m for m in matches if m.get("score", 0) >= 0.90]
            if len(exact) == 1:
                match = exact[0]
                totals = {}
                for item, amount in match.get("ingredients", []):
                    totals[item] = totals.get(item, 0) + int(amount) * batch_count
                embed = discord.Embed(title=f"🧾 Shopping list: {batch_count:,} × {match['recipe']}", color=COLOR)
                embed.add_field(name="Crafting table", value=match["table"], inline=False)
                embed.add_field(name="Ingredients required", value="\n".join(f"• **{name}:** {amount:,}" for name, amount in totals.items())[:1024] or "No ingredients recorded.", inline=False)
                if match.get("tools"):
                    embed.add_field(name="Tools (not consumed)", value=", ".join(match["tools"]), inline=False)
                embed.set_footer(text="Calculated from the saved recipe directory • Tools are not multiplied")
                await message.reply(embed=embed, mention_author=False)
                return
            if len(exact) > 1 or matches:
                names = "\n".join(f"• **{m['recipe']}** — {m['table']}" for m in matches[:4])
                await message.reply("I found multiple possible recipes. Please use the exact recipe name:\n" + names, mention_author=False)
                return

    # Inventory-based batch calculator works for every saved recipe, not one hard-coded item.
    stock_match = re.search(r"\bwith\s*:?\s*(.+)$", query, re.IGNORECASE)
    if stock_match and any(word in lowered for word in ("how many", "how much", "can i make", "can i craft", "make from")):
        try:
            stock = parse_inventory(stock_match.group(1))
        except ValueError as exc:
            await message.reply(f"Inventory format error: {exc}", mention_author=False)
            return
        possible = []
        for table in query_data.get("tables", []):
            for recipe in table.get("recipes", []):
                required = {}
                for item, amount in recipe.get("ingredients", []):
                    required[item] = required.get(item, 0) + int(amount)
                if not required:
                    continue
                batches = min((inventory_quantity(stock, item) // amount for item, amount in required.items()), default=0)
                if batches:
                    possible.append((batches, recipe.get("name", "Unknown"), table.get("name", "Unknown"), list(recipe.get("notes") or [])))
        possible.sort(key=lambda row: (-row[0], row[1].casefold()))
        if possible:
            lines = [
                f"• **{name}** — {count:,} batch(es) · {table}"
                + (("\n  ⚠️ " + " ".join(notes)) if notes else "")
                for count, name, table, notes in possible[:20]
            ]
            await message.reply("**Recipes covered by your listed stock (recorded ingredients):**\n" + "\n".join(lines), mention_author=False)
        else:
            await message.reply("Your listed stock does not cover a complete saved recipe. Try adding more inventory or check /crafting.", mention_author=False)
        return

    related_prefixes = ("what tables", "which tables", "tables related", "related tables", "what table", "which table")
    if query.casefold().startswith(related_prefixes) or ("table" in query.casefold() and any(term in query.casefold() for term in ("weed", "marijuana", "cannabis", "bud"))):
        data = get_guild_recipe_data(message.guild.id if message.guild else None)
        results = related_table_search(query_data, query, limit=8)
        if not results:
            await message.reply("I couldn't find related tables in the saved recipe directory. Try a different keyword or use /dashboard to browse.", mention_author=False)
            return
        embed = discord.Embed(
            title=f"Related crafting tables: {query[:120]}",
            description="Closest matches from the saved recipe directory. Only existing tables and recipes are shown.",
            color=COLOR,
        )
        for result in results:
            recipe_lines = []
            for recipe in result["recipes"][:8]:
                ingredients = ", ".join(recipe["ingredients"][:8]) or "No ingredients recorded"
                recipe_lines.append(f"• **{recipe['recipe']}** — {ingredients}")
                recipe_lines.extend(f"  ⚠️ {note}" for note in recipe.get("notes", []))
            embed.add_field(
                name=f"{result['table']} · {len(result['recipes'])} match(es)"[:256],
                value="\n".join(recipe_lines)[:1024] or "No matching recipes recorded.",
                inline=False,
            )
        embed.set_footer(text="FJORD CARTEL • Related matches are based on saved recipe names and ingredients")
        await message.reply(embed=embed, mention_author=False)
        return

    if query.casefold().startswith(("what can i craft", "what can i make", "what can i produce")):
        if ":" in query:
            raw_stock = query.split(":", 1)[1]
        else:
            stock_match = re.search(r"\bwith\s+(.+)$", query, re.IGNORECASE)
            raw_stock = stock_match.group(1) if stock_match else ""
        if not raw_stock:
            await message.reply("Use !what can I craft with Item x10, Item x5 (or use a colon before the inventory).", mention_author=False)
            return
        raw_stock = raw_stock.strip().rstrip("?.!")
        try:
            stock = parse_inventory(raw_stock)
        except ValueError as exc:
            await message.reply(f"Inventory format error: {exc}", mention_author=False)
            return
        data = get_guild_recipe_data(message.guild.id if message.guild else None)
        craftable = []
        for table in query_data.get("tables", []):
            for recipe in table.get("recipes", []):
                needed = {}
                for name, qty in recipe.get("ingredients", []):
                    needed[name] = needed.get(name, 0) + int(qty)
                batches = min((inventory_quantity(stock, name) // qty for name, qty in needed.items()), default=0)
                if batches > 0:
                    craftable.append((batches, table.get("name", "Unknown"), recipe.get("name", "Unknown"), list(recipe.get("notes") or [])))
        craftable.sort(key=lambda row: (-row[0], row[2].casefold()))
        if not craftable:
            await message.reply("Your stock does not cover a complete recorded recipe yet. Try /dashboard to browse the directory.", mention_author=False)
        else:
            lines = [
                f"• **{name}** — {batches} batch(es) · {table}"
                + (("\n  ⚠️ " + " ".join(notes)) if notes else "")
                for batches, table, name, notes in craftable[:20]
            ]
            await message.reply("**Recipes covered by your listed stock (recorded ingredients):**\n" + "\n".join(lines), mention_author=False)
        return

    record_usage("search", query)
    aliases = guild_aliases(message.guild.id if message.guild else None)
    alias_target = next((target for alias, target in aliases.items() if alias.casefold() == query.casefold()), None)
    matches = chat_recipe_search(query_data, alias_target or query, limit=5)

    # Hybrid mode: deterministic lookups remain authoritative; the AI only
    # interprets the question and explains relevant saved facts.
    if hybrid_ai_is_configured():
        context_parts = []
        for item in matches[:5]:
            recipe_name = str(item.get("recipe", "Unknown"))
            table_name = str(item.get("table", "Unknown"))
            context_parts.append(f"Recipe: {recipe_name} | Table: {table_name}")
            restricted = any(term in (recipe_name + " " + table_name).casefold() for term in (
                "heroin", "fentanyl", "carfentanil", "cartentanil", "methadone",
                "hydrocodone", "oxymorphone", "pethidine", "xylazine", "krakadil",
                "isotonitazine", "anpp", "codeine", "opioid", "pill press",
            ))
            if not restricted:
                context_parts.append("Recorded ingredients: " + ", ".join(
                    f"{name} x{quantity}" for name, quantity in item.get("ingredients", [])
                ))
                context_parts.append("Recorded tools: " + ", ".join(item.get("tools", [])))
            if item.get("notes"):
                context_parts.append("Data notes: " + "; ".join(str(note) for note in item["notes"]))
        info_matches = saved_information_matches(query)
        for item in info_matches[:8]:
            context_parts.append(
                f"{item['source']} — {item['title']}: {item['value']}"
            )
        try:
            ai_answer = await hybrid_ai_answer(
                message.guild.id, message.author.id, query, "\\n".join(context_parts)
            )
        except Exception:
            logger.exception("Hybrid AI answer handler failed")
            ai_answer = None
        if ai_answer:
            await message.reply(ai_answer, mention_author=False)
            return

    if not matches:
        record_usage("no_result", query)
        await message.reply(
            f"I couldn't find a close match for **{query[:100]}**. Try a shorter item name, check the spelling, or use /dashboard to browse.",
            mention_author=False,
        )
        return

    if len(matches) == 1:
        match = matches[0]
        ingredient_lines = [f"• **{name}** ×{quantity}" for name, quantity in match.get("ingredients", [])]
        description = f"**Table:** {match['table']}\n**Recipe:** {match['recipe']}\n**Ingredients:**\n" + ("\n".join(ingredient_lines) if ingredient_lines else "None recorded")
        if match.get("tools"):
            description += "\n**Tools (not consumed):** " + ", ".join(match["tools"])
        if match.get("notes"):
            description += "\n\n**Data review notes:**\n" + "\n".join(f"• {note}" for note in match["notes"])
        embed = discord.Embed(title=f"Crafting match: {match['recipe'][:180]}", description=description[:4000], color=COLOR)
        embed.set_footer(text="Game reference only • Use /dashboard for the full directory")
        await message.reply(embed=embed, mention_author=False)
        return

    embed = discord.Embed(
        title=f"Possible crafting matches: {query[:160]}",
        description="I found a few close matches. Choose the item you meant from the dropdown.",
        color=COLOR,
    )
    for match in matches:
        embed.add_field(
            name=f"{match['recipe']} • {match['table']}"[:256],
            value=match.get("match_label", "Closest match") + (("\n⚠️ " + " ".join(match.get("notes", []))) if match.get("notes") else ""),
            inline=False,
        )
    embed.set_footer(text="Spelling suggestions only • Original recipe names are unchanged")
    await message.reply(embed=embed, view=ChatRecipeMatchView(message.author.id, query, matches), mention_author=False)

def dashboard_embed():
    embed = discord.Embed(
        title="⚔️ Fjord Cartel Information",
        description="**PRIVATE MEMBER DASHBOARD**\n\nWelcome to the Fjord Cartel directory. Select a section from the menu below.",
        color=COLOR,
    )
    embed.set_footer(text="FJORD CARTEL • BLOOD IN THE WATER, STEEL IN THE VEINS")
    return embed


async def return_to_dashboard(interaction: discord.Interaction, owner_id: int):
    await interaction.response.edit_message(
        embed=dashboard_embed(),
        view=DashboardMenuView(owner_id),
    )


def shops_embed():
    embed = discord.Embed(
        title="🛒 Fjord Cartel • Shops (Listed)",
        description="Shop directory • Item prices.",
        color=COLOR,
    )
    embed.add_field(
        name="📱 Digital Den (Electronics)",
        value=(
            "• **Phone:** $500\n"
            "• **Radio:** $500\n"
            "• **Laptop:** $2,000"
        ),
        inline=False,
    )
    embed.add_field(
        name="🔫 Weapon & Ammo Store",
        value=(
            "**Ammo**\n"
            "• **Pistol Ammo:** $10\n"
            "• **Rifle Ammo (5.56):** $20\n"
            "• **SMG Ammo (.45 ACP):** $23\n"
            "• **Rifle Ammo (7.62):** $25\n"
            "• **Shotgun Ammo (12 Gauge):** $55\n\n"
            "**Pistol Weapons**\n"
            "• **Black Pistol:** $2,000\n"
            "• **Pink Pistol:** $4,800\n\n"
            "**Melee Weapons**\n"
            "• **Snowball:** $100\n"
            "• **Bat:** $250\n"
            "• **Knife:** $250"
        ),
        inline=False,
    )
    embed.add_field(
        name="🚗 PDM",
        value=(
            "• **Repair Kits:** $2,000\n"
            "• **Contracts:** $1,000 *(Special Role Required)*"
        ),
        inline=False,
    )
    embed.add_field(
        name="🏪 Convenience Store",
        value=(
            "**Misc**\n"
            "• **Lockpick:** $20\n"
            "• **Jerry Can:** $200\n"
            "• **Outfit Bag:** $5,000\n\n"
            "**Chips**\n"
            "• **Classic Chips:** $3\n"
            "• **Cheese Chips:** $3\n"
            "• **Salted Chips:** $3\n"
            "• **Ribs Chips:** $4\n"
            "• **Habanero Chips:** $5\n\n"
            "**Cigarettes**\n"
            "• **Redwood Cigarettes:** $5\n"
            "• **Vape:** $1,000\n\n"
            "**Meals**\n"
            "• **Hot Dog:** $2\n"
            "• **Homemade Sandwich:** $3\n"
            "• **Chicken Noodles:** $3\n"
            "• **Seafood Noodles:** $3\n\n"
            "**Drinks**\n"
            "• **E-Cola:** $3\n"
            "• **E-Cola Light:** $3\n"
            "• **Orang-O-Tang:** $3\n"
            "• **Sprunk:** $3\n"
            "• **Sprunk Bottle:** $3\n"
            "• **Sprunk Light:** $4\n"
            "• **E-Cola Bottle:** $4\n"
            "• **Orang-O-Tang Bottle:** $4\n"
            "• **E-Cola Light Bottle:** $5\n"
            "• **Sprunk Light Bottle:** $5"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎉 Head Shop — Postal 3057",
        value=(
            "**Kitchen (4 items)**\n"
            "• **Cookie dough:** $75 each\n"
            "• **Chocolate chips:** $50 each\n"
            "• **Baking soda:** $10 each\n"
            "• **Grapeseed Oil:** $25 each\n\n"
            "**Packaging (4 items)**\n"
            "• **Plastic bag:** $5 each\n"
            "• **Styrofoam Cup:** $15 each\n"
            "• **2L Plastic Bottle:** $5 each\n"
            "• **Aluminum Foil:** $10 each\n\n"
            "**Smoking & Party (6 items)**\n"
            "• **Art papers:** $150 each\n"
            "• **Nitrous Oxide Charger:** $15 each\n"
            "• **Balloon:** $5 each\n"
            "• **Cigarette:** $5 each\n"
            "• **Weed papers:** $30 each\n"
            "• **Pipe:** $10 each\n\n"
            "**Lab Gear & Safety (1 item)**\n"
            "• **Cheesecloth:** $5 each"
        ),
        inline=False,
    )
    embed.add_field(
        name="💊 Pharmacy — Postal 9072",
        value=(
            "**Medical & Wellness (9 items)**\n"
            "• **Bandage:** $150 each\n"
            "• **Feminine Pad:** $10 each\n"
            "• **Chill Pills:** $100 each\n"
            "• **Electrolyte Drink:** $20 each\n"
            "• **Cough Syrup:** $50 each\n"
            "• **Condoms:** $10 each\n"
            "• **Pregnancy Test Box:** $200 each\n"
            "• **Prenatal Vitamins:** $100 each\n"
            "• **Baby Oil:** $50 each\n\n"
            "**Party & Gender Reveal (5 items)**\n"
            "• **Confetti Cannon:** $50 each\n"
            "• **Confetti Popper:** $50 each\n"
            "• **Gender Reveal Balloon:** $50 each\n"
            "• **Gender Reveal Gift Box:** $50 each\n"
            "• **Gender Reveal Smoke:** $50 each"
        ),
        inline=False,
    )
    embed.add_field(
        name="🥕 Farmers Market",
        value=(
            "• **Bag of Corn:** $10\n"
            "• **Bag of Sugar:** $10\n"
            "• **Bag of Yeast:** $10\n"
            "• **Gallon of Water:** $5\n"
            "• **Empty Barrel:** $100\n"
            "• **Empty Jug:** $50"
        ),
        inline=False,
    )
    embed.add_field(
        name="🪵 Log Market — Postal 1082",
        value="• **Firewood:** $10",
        inline=False,
    )
    embed.add_field(
        name="🤿 Scuba Diving Shop",
        value=(
            "**Salvage & Finds**\n"
            "• **Old Boot:** $15\n"
            "• **Wood Plank:** $15\n"
            "• **Rusted Padlock:** $15\n"
            "• **Rusted Key:** $15\n"
            "• **Rusted Gear:** $15\n"
            "• **Seashell:** $43\n"
            "• **Seaweed:** $43\n"
            "• **Rusted Muffler:** $43\n"
            "• **Broken CD:** $43\n"
            "• **Diving Goggles:** $43\n"
            "• **Fishing Net:** $70\n"
            "• **Old Camera:** $70\n"
            "• **Military Helmet:** $70\n"
            "• **Old Compass:** $93\n"
            "• **Old Watch:** $93\n"
            "• **Conch Shell:** $93\n"
            "• **Bottle of Rum:** $26 *(or $28; price varies)*\n"
            "• **Treasure Map:** $40\n"
            "• **Silver Bracelet:** $55\n"
            "• **Ancient Artifact:** $78"
        ),
        inline=False,
    )
    embed.add_field(
        name="⚓ The Gear Shop",
        value=(
            "**Items to Purchase**\n"
            "• **Oxygen Tank:** $100\n"
            "• **Scuba Gear | Level 1:** $250\n"
            "• **Scuba Gear | Level 2:** $500\n"
            "• **Scuba Gear | Level 3:** $1,000\n"
            "• **Scuba Gear | Level 4:** $2,000\n"
            "• **Scuba Gear | Level 5:** $5,000\n"
            "• **Burger:** $5\n"
            "• **Water:** $5\n\n"
            "**Boat Rental**\n"
            "• **24-hour rental:** $500 deposit\n"
            "• Deposit is refunded when the boat is returned."
        ),
        inline=False,
    )
    embed.set_footer(text="FJORD CARTEL • SHOP DIRECTORY")
    return embed


def locations_embed():
    embed = discord.Embed(
        title="📍 Fjord Cartel • Locations/Shops (Hidden)",
        description="Saved location references for cartel members. Farm Supplier: Postals 2002–2003 • Hangar/Barn: Postals 2029–2030.",
        color=COLOR,
    )
    embed.add_field(
        name="Farm Supplier — Postals 2002–2003 • Seeds & Cuttings (5)",
        value=(
            "• **Weed seed:** $60 each\n"
            "• **Cocaine seed:** $150 each\n"
            "• **Poppy seeds:** $120 each\n"
            "• **Birch Sapling:** $200 each\n"
            "• **San Pedro Cuttings:** $90 each"
        ),
        inline=False,
    )
    embed.add_field(
        name="Farm Supplier • Water (5)",
        value=(
            "• **Watering can:** $15 each\n"
            "• **Rainwater Jug:** $20 each\n"
            "• **Spring Water:** $25 each\n"
            "• **Pond Water:** $15 each\n"
            "• **Misting Bottle:** $20 each"
        ),
        inline=False,
    )
    embed.add_field(
        name="Farm Supplier • Fertilizer & Soil (11)",
        value=(
            "• **Fertilizer:** $40 each\n"
            "• **Cactus Fertilizer:** $50 each\n"
            "• **Tropical Fertilizer:** $60 each\n"
            "• **Fish Emulsion:** $50 each\n"
            "• **Bone Meal:** $45 each\n"
            "• **Bloom Booster:** $70 each\n"
            "• **Organic Compost:** $55 each\n"
            "• **Birch Leaf Mulch:** $45 each\n"
            "• **Aquatic Fertilizer Tabs:** $50 each\n"
            "• **Cactus Soil Mix:** $40 each\n"
            "• **Peat Moss:** $40 each"
        ),
        inline=False,
    )
    embed.add_field(
        name="Farm Supplier • Grow Gear (7)",
        value=(
            "• **Trowel:** $100 each\n"
            "• **Flower Pot:** $250 each\n"
            "• **Portable Lamp (Standard):** $750 each\n"
            "• **Portable Lamp (Large):** $1,250 each\n"
            "• **Garden Trellis:** $150 each\n"
            "• **Shade Cloth:** $120 each\n"
            "• **Pond Tub:** $250 each"
        ),
        inline=False,
    )
    embed.add_field(
        name="Farm Supplier • Precursors (1)",
        value="• **Piperazine:** $80 each",
        inline=False,
    )
    embed.add_field(
        name="Farm Supplier • Kitchen (1)",
        value="• **Whole Nutmeg:** $10 each",
        inline=False,
    )
    embed.add_field(
        name="Farm Supplier • Tools & Phones (1)",
        value="• **Mortar and Pestle:** $60 each",
        inline=False,
    )
    embed.add_field(
        name="Hangar/Barn — Postals 2029–2030 • Greenhouse Tables (6)",
        value=(
            "• **Greenhouse tables: dry salvia**\n"
            "• **Greenhouse tables: dry kava**\n"
            "• **Greenhouse tables: dry kratom**\n"
            "• **Greenhouse tables: dry weed**\n"
            "• **Greenhouse tables: dry iboga**\n"
            "• **Greenhouse tables: dry blue lotus**"
        ),
        inline=False,
    )
    embed.add_field(
        name="Chemical Supplier — Postal 10105 • Train Side",
        value=(
            "Single person under the concrete walkway on the train side; sells liquid ingredients such as distilled water.\n\n"
            "**Acids & Bases (5 items)**\n"
            "• **Sodium Hydroxide (Lye):** $80 each\n"
            "• **Citric Acid:** $20 each\n"
            "• **Sulfuric Acid:** $50 each\n"
            "• **Slaked Lime:** $15 each\n"
            "• **Succinic Acid:** $40 each"
        ),
        inline=False,
    )
    embed.add_field(
        name="Solvents (6 items)",
        value=(
            "• **Acetone:** $60 each\n"
            "• **Isopropyl Alcohol:** $50 each\n"
            "• **Distilled Water:** $20 each\n"
            "• **Naphtha:** $70 each\n"
            "• **Grain Alcohol:** $45 each\n"
            "• **Butane Canister:** $30 each"
        ),
        inline=False,
    )
    embed.add_field(
        name="Reagents (7 items)",
        value=(
            "• **Sodium Benzoate:** $150 each\n"
            "• **Ammonia:** $175 each\n"
            "• **Hydrogen Peroxide:** $40 each\n"
            "• **Urea:** $25 each\n"
            "• **Formaldehyde:** $60 each\n"
            "• **Potassium Permanganate:** $60 each\n"
            "• **Sodium Acetate:** $40 each"
        ),
        inline=False,
    )
    embed.add_field(
        name="Lab Gear & Safety (1 item)",
        value="• **Filter Paper:** $10 each",
        inline=False,
    )
    embed.add_field(
        name="Coke Island",
        value="In the water roughly between Humane Labs and Davis Quartz.",
        inline=False,
    )
    embed.add_field(
        name="Other Hidden Island",
        value="Another hidden island with nothing on it.",
        inline=False,
    )
    embed.add_field(
        name="Cayo Perico Island",
        value="Cayo Perico Island.",
        inline=False,
    )
    embed.add_field(
        name="Rotating NPC — Old Man",
        value="• **Moonshine:** Sell Moonshine to the Old Man. His location rotates and is marked on the map.",
        inline=False,
    )
    embed.add_field(
        name="Hidden Location • RVs — Postal 4024",
        value=(
            "• **Cook Meth:** Use the RV location at Postal 4024.\n"
            "• **Other RVs/Campers:** Meth can also be cooked in any RV or Camper you find or purchase."
        ),
        inline=False,
    )
    embed.add_field(
        name="1000s Postal Codes — Hidden Locations",
        value=(
            "• **1012 — Propane:** Orange gas station next to the compound, near the garage. Buy propane for $1,000; sell empty container for $300.\n"
            "• **1016–1018 & 9241 — Box Collection:** Collect boxes, then take them to the NPC to trade the boxes for materials.\n"
            "• **1017–1019 — NPC Pickup Supplies:** Random guy/pickup supplies. Access and details unconfirmed.\n"
            "• **9062 — Pickup Supplies.**\n"
            "• **8175 — Hooker.**\n"
            "• **8042 — Hookers.**\n"
            "• **7281 — Empty Lab.**\n"
            "• **1026–1050 — Random Locked Door:** Exact location/activity unknown; verify postal range.\n"
            "• **Drug Runs — Mysterious Person:** Drug runs are marked on the map as \"Mysterious Person\".\n"
            "• **1056 — Empty Lab:** White side door, opposite the fishing guy. Possibly owned; ownership unconfirmed.\n"
            "• **1058 — Empty Lab.**\n"
            "• **1082 — Pick Wild Amanita.**"
        ),
        inline=False,
    )
    embed.add_field(
        name="2000s Postal Codes — Equipment & Locations",
        value=(
            "• **2048 — Empty Lab.**\n"
            "• **2006 — Meth Cooking Station:** $15,000.\n"
            "• **2006 — Gasoline:** Collect gasoline.\n"
            "• **2060 — Ammonia Tanks.**\n"
            "• **2006 — RV Meth Cooking Kit:** $10,000.\n"
            "• **2006 — Ethanol Distiller:** $25,000.\n"
            "• **2006 — Propane:** Also listed as a propane buy/sell postal in the earlier location notes.\n"
            "• **Grapeseed Airport — Hangar:** Weed cleaning table."
        ),
        inline=False,
    )
    embed.add_field(
        name="3000s Postal Codes — Hidden Locations",
        value=(
            "• **3009 — Blackmarket Doctor:** Supplier with the items and prices listed below.\n"
            "  **Precursors:** Safrole oil ($200), NPP chemical ($300), Aniline solution ($250).\n"
            "  **Pharmaceuticals:** Anesthetic ($250), Dextromethorphan Cough Syrup ($60).\n"
            "  **Packaging:** Syringe ($15).\n"
            "• **3009 — Desert Still.**\n"
            "• **3026 — Liquor Store:** Collect Acetone, Rubbing Alcohol & Pseudoephedrine. Caution: An NPC may attack when you go around the back.\n"
            "• **3042 — Shed:** Meth cooking / rubbing alcohol distiller; turns rubbing alcohol into ethanol.\n"
            "• **3048 — Recycling Yard:** Battery acid. Third-eye batteries on the ground to get acid; junked cars can also give lithium batteries or corroded batteries. Landmark wording needs verification.\n"
            "• **3028 — Empty Lab.**\n"
            "• **3051 — Side of Gas Station:** Gang paint ($200,000) / cleaner ($40,000)."
        ),
        inline=False,
    )
    embed.add_field(
        name="Head Shop — Postal 3057",
        value="Head Shop supplier. See the Shops & Prices section for its 15 listed items and prices.",
        inline=False,
    )
    embed.add_field(
        name="4000s Postal Codes — Hidden Locations",
        value=(
            "• **4001 — Prison tunnel.**\n"
            "• **4013 — Meth Cooking Kit:** Be careful; an NPC will attack.\n"
            "• **4013–4014 — Cement:** Collect cement.\n"
            "• **4019 — Empty Lab.**"
        ),
        inline=False,
    )
    embed.add_field(
        name="Equipment Dealer — Postals 9275–9277",
        value=(
            "**Workstations (13 items)**\n"
            "• **Meth table:** $5,000 each\n"
            "• **Weed table:** $4,000 each\n"
            "• **Coke table:** $5,000 each\n"
            "• **Chemistry table:** $6,500 each\n"
            "• **Pill Press:** $7,500 each\n"
            "• **Reflux Rig:** $9,000 each\n"
            "• **Extraction Bench:** $8,000 each\n"
            "• **Glovebox:** $15,000 each\n"
            "• **Brewing Kettle:** $2,500 each\n"
            "• **Lab Freezer:** $4,000 each\n"
            "• **Herb Drying Rack:** $2,000 each\n"
            "• **Grinding Station:** $3,000 each\n"
            "• **Capsule Filler:** $3,500 each\n\n"
            "**Tools & Phones (3 items)**\n"
            "• **Burner phone:** $500 each\n"
            "• **Tablet Die Set:** $1,200 each\n"
            "• **Hand Tablet Press:** $900 each"
        ),
        inline=False,
    )
    embed.add_field(
        name="9000s Postal Codes — Hidden Locations",
        value=(
            "• **9035:** Guy near the Long Pig Mini Market — gang spray and removal.\n"
            "• **9050:** Under the bridge — Hobo King / scrap collector.\n"
            "• **9051 — Gasoline:** Collect gasoline.\n"
            "• **9093:** Near Postal 9187, side entrance on blue trailer — Coke lab.\n"
            "• **9120:** Hobo bowling.\n"
            "• **9142:** Behind Cluckin' Bell — sell stolen phones.\n"
            "• **9195 — Lab:** Tables #1–#4; browse the saved table and recipe directory in `/crafting`.\n"
            "• **9275:** Press machine.\n"
            "• **9366:** Empty Lab.\n"
            "• **9379:** Weed lab; reported inactive, no activity found."
        ),
        inline=False,
    )
    embed.add_field(
        name="10000s Postal Codes — Crafting Bench",
        value="• **10060 — Second Floor:** Crafting bench / scrapyard bench for thermites, drills, advanced lockpicks, and other items.",
        inline=False,
    )
    embed.add_field(
        name="10060 Crafting Bench — Basic Components & Materials",
        value=(
            "• **Metal Pin (+3 XP):** 8x material_iron + 4x material_steel\n"
            "• **Tension Spring (+3 XP):** 10x material_steel + 6x material_aluminum\n"
            "• **Nylon Weave (+3 XP):** 24x material_plastic + 10x material_rubber\n"
            "• **Optical Lens (+5 XP):** 20x material_glass + 10x material_plastic\n"
            "• **Honed Blade (+8 XP):** 14x material_steel + 10x material_iron\n"
            "• **Hardened Alloy (+10 XP):** 20x material_steel + 12x material_aluminum + 5x material_copper"
        ),
        inline=False,
    )
    embed.add_field(
        name="10060 Crafting Bench — Tools & Gear",
        value=(
            "• **Tungsten Drill Bit (+12 XP):** 2x hardened_alloy + 8x material_copper + 40x material_metalscrap + 1 hidden material\n"
            "• **Lockpick (+12 XP):** 2x metal_pin + 1x tension_spring + 6x material_plastic\n"
            "• **Rope (+12 XP):** 3x nylon_weave + 10x material_rubber\n"
            "• **Crowbar (+10 XP):** 25x material_iron + 8x material_rubber + 1x hardened_alloy\n"
            "• **Binoculars (+10 XP):** 2x optical_lens + 1x tension_spring + 20x material_plastic + 1 hidden material\n"
            "• **Parachute (+10 XP):** 8x nylon_weave + 2x rope + 2x tension_spring + 1 hidden material"
        ),
        inline=False,
    )
    embed.add_field(
        name="10060 Crafting Bench — Advanced Tools & Weapons",
        value=(
            "• **Advanced Lockpick (+15 XP):** 4x metal_pin + 2x tension_spring + 1x hardened_alloy + 1 hidden material\n"
            "• **Brass Knuckles (+15 XP):** 2x hardened_alloy + 20x material_metalscrap + 6x material_rubber\n"
            "• **Switchblade (+15 XP):** 1x honed_blade + 1x hardened_alloy + 1x tension_spring + 1 hidden material\n"
            "• **Improvised Handcuffs (+20 XP):** 4x metal_pin + 2x tension_spring + 1x hardened_alloy + 1 hidden material\n"
            "• **Heist Drill (+15 XP):** 2x drill_bit + 3x hardened_alloy + 2x tension_spring + 1 hidden material\n"
            "• **Vector (+15 XP):** 2,000x material_metalscrap + 2,000x material_iron\n"
            "• **NV Rifle (+15 XP):** 2,500x material_metalscrap + 2,500x material_iron\n"
            "• **Thermite (+10 XP):** 200x material_metalscrap + 200x material_iron"
        ),
        inline=False,
    )
    embed.add_field(
        name="10060 Crafting Bench — Data Review",
        value=(
            "Some items in the location notes include an additional '1 hidden material', but the exact item name is not recorded in the saved Crafting Bench recipes. "
            "The Heist Drill recipe also uses the item name 'drill_bit', while the saved output is named 'Tungsten Drill Bit'. "
            "These details are flagged for review rather than guessed."
        ),
        inline=False,
    )
    embed.add_field(
        name="5000s Postal Codes — Pickups",
        value="• **5000 — Morning Glory:** Pick Morning Glory Seed Pods.",
        inline=False,
    )
    embed.add_field(
        name="7000s Postal Codes — Pickups",
        value="• **7001 — Gasoline:** Collect gasoline.",
        inline=False,
    )
    embed.add_field(
        name="8000s Postal Codes — Street Pickups",
        value=(
            "• **8182 — Chemical Pickup:** Grab Hydrochloric Acid & Ammonia.\n"
            "• **5024 — Urea Fertilizer:** Pick Urea Fertilizer.\n"
            "• **8040 — Vials & Syringes:** Search black trash bags on the street.\n"
            "• **8254 — Gasoline:** Collect gasoline."
        ),
        inline=False,
    )
    embed.set_footer(text="FJORD CARTEL • HIDDEN LOCATIONS • SEE POSTAL REFERENCES ABOVE")
    return embed


def usable_embed():
    embed = discord.Embed(
        title="🎒 Fjord Cartel • Usable Items",
        description="Items that can be used from a player's FiveM inventory, with the required materials.",
        color=COLOR,
    )
    embed.add_field(
        name="🛍️ Plastic Bag",
        value=(
            "• **Meth bag** — 10x Meth + 1x Plastic bag\n"
            "• **Cocaine bag** — 10x Raw Cocaine + 1x Plastic bag\n"
            "• **Crack bag** — 10x Crack + 1x Plastic bag\n"
            "• **Weed bag** — 10x Clean weed bud + 1x Plastic bag\n"
            "• **Heroin bag** — 10x Heroin + 1x Plastic bag\n"
            "• **Ketamine bag** — 10x Ketamine + 1x Plastic bag\n"
            "• **Fentanyl bag** — 10x Fentanyl + 1x Plastic bag\n"
            "• **Bag of Blue Crystal** — 10x Blue Crystal + 1x Plastic bag"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎨 Art Papers",
        value=(
            "• **LSD Tab** — 1x LSD Liquid + 1x Art papers\n"
            "• **25I-NBOMe** — 1x NBOMe Solution + 1x Art papers\n"
            "• **1P-LSD** — 1x 1P-LSD Solution + 1x Art papers"
        ),
        inline=False,
    )
    embed.add_field(
        name="🥤 Styrofoam Cup",
        value="• **Lean** — 1x Promethazine-Codeine Syrup + 1x Sprunk + 2x Styrofoam Cup",
        inline=False,
    )
    embed.add_field(
        name="🧴 2L Water Bottle",
        value=(
            "• **Meth** — 4x Pseudoephedrine + 1x Ammonia + 1x Sodium Hydroxide (Lye) + 1x 2L Water Bottle\n"
            "  **Tool (not consumed):** 1x Gas Mask"
        ),
        inline=False,
    )
    embed.add_field(
        name="💉 Syringe",
        value=(
            "• **Meth syringe** — 5x Meth + 1x Syringe\n"
            "• **Crack syringe** — 5x Crack + 1x Syringe\n"
            "• **Heroin syringe** — 5x Heroin + 1x Syringe\n"
            "• **Krokodil Shot** — 1x Krokodil + 1x Syringe\n"
            "• **Speedball** — 3x Heroin + 3x Raw Cocaine + 1x Syringe"
        ),
        inline=False,
    )
    embed.add_field(
        name="💊 Hand Tablet Press — Pill Recipes (1/2)",
        value=(
            "• **Xanax** — 1x Alprazolam Powder + 1x Pill Binder\n"
            "• **Valium** — 1x Diazepam Powder + 1x Pill Binder\n"
            "• **Adderall** — 1x Amphetamine Powder + 1x Pill Binder\n"
            "• **Quaaludes** — 1x Methaqualone Powder + 1x Pill Binder\n"
            "• **Tramadol** — 1x Tramadol HCl + 1x Pill Binder\n"
            "• **Ritalin** — 1x Methylphenidate Powder + 1x Pill Binder\n"
            "• **Captagon** — 1x Fenethylline Powder + 1x Pill Binder\n"
            "• **Modafinil** — 1x Modafinil Powder + 1x Pill Binder"
        ),
        inline=False,
    )
    embed.add_field(
        name="💊 Hand Tablet Press — Pill Recipes (2/2)",
        value=(
            "• **DOM** — 1x DOM Powder + 1x Pill Binder\n"
            "• **Dilaudid** — 1x Hydromorphone HCl + 1x Pill Binder\n"
            "• **Opana** — 1x Oxymorphone HCl + 1x Pill Binder\n"
            "• **Klonopin** — 1x Clonazepam Powder + 1x Pill Binder\n"
            "• **Ambien** — 1x Zolpidem Powder + 1x Pill Binder\n"
            "• **Soma** — 1x Carisoprodol Powder + 1x Pill Binder\n"
            "• **6-APB** — 1x 6-APB Succinate + 1x Pill Binder\n"
            "• **BZP** — 1x BZP HCl + 1x Pill Binder\n"
            "• **Ecstasy pill** — 1x Ecstasy crystals + 1x Pill Binder\n"
            "• **Hydrocodone** — 1x Hydrocodone Bitartrate + 2x Acetaminophen + 1x Pill Binder"
        ),
        inline=False,
    )
    embed.add_field(
        name="📝 Item Name Check",
        value=(
            "The Usable Items entry is named **2L Water Bottle**. The Head Shop price list is named **2L Plastic Bottle**. "
            "The saved information does not confirm these are the same item, so their names and prices are kept separate."
        ),
        inline=False,
    )
    embed.set_footer(text="FJORD CARTEL • USABLE ITEM DIRECTORY")
    return embed


def include_usable_item_recipes(data: dict):
    """Combine saved crafting tables and usable-item recipes without mutating source data."""
    combined = attach_location_recipe_warnings(
        data,
        [(field.name, field.value) for field in locations_embed().fields],
    )
    tables = list(combined.get("tables", []))
    sections = [(field.name, field.value) for field in usable_embed().fields]
    usable_tables = parse_usable_item_sections(sections)
    for table in usable_tables:
        for recipe in table.get("recipes", []):
            recipe["notes"] = []
            if any(str(name).casefold() == "2l water bottle" for name, _ in recipe.get("ingredients", [])):
                recipe["notes"].append(
                    "The Usable Items page calls this ingredient '2L Water Bottle', while the Head Shop list calls its item '2L Plastic Bottle'. "
                    "The saved information does not confirm they are the same item, so the Head Shop price is not assumed to apply."
                )
    tables.extend(usable_tables)
    combined["tables"] = tables
    return combined


def saved_information_matches(query: str):
    """Search the same saved information pages exposed through slash commands."""
    normalized = re.sub(r"[^a-z0-9]+", " ", str(query or "").casefold()).strip()
    ignored = {
        "where", "what", "whats", "how", "do", "does", "i", "you", "is", "are",
        "the", "a", "an", "to", "for", "me", "please", "can", "could", "tell",
        "about", "find", "get", "buy", "use", "used", "sell", "at", "in", "on",
        "my", "your", "and", "of", "it", "this", "that", "item", "located", "location", "postal", "postals", "code",
    }
    terms = [word for word in normalized.split() if len(word) > 1 and word not in ignored]
    if not terms:
        return []
    sources = (
        ("Shops", shops_embed()),
        ("Locations", locations_embed()),
        ("Usable Items", usable_embed()),
        ("Commands", commands_embed()),
    )
    matches = []
    for source_name, embed in sources:
        for field in embed.fields:
            title_norm = re.sub(r"[^a-z0-9]+", " ", field.name.casefold()).strip()
            value_lines = field.value.splitlines()
            value_norm = re.sub(r"[^a-z0-9]+", " ", field.value.casefold()).strip()
            hits = [term for term in terms if term in (title_norm + " " + value_norm).split()]
            if not hits:
                continue
            if len(terms) > 1 and len(hits) < len(terms):
                continue
            if all(term in title_norm.split() for term in terms):
                selected_value = field.value
            else:
                selected_lines = [
                    line for line in value_lines
                    if any(term in re.sub(r"[^a-z0-9]+", " ", line.casefold()).split() for term in terms)
                ]
                selected_value = "\n".join(selected_lines) if selected_lines else field.value
            matches.append({
                "source": source_name,
                "title": field.name,
                "value": selected_value,
                "score": len(hits),
            })
    matches.sort(key=lambda item: (-item["score"], item["source"], item["title"].casefold()))
    return matches


def commands_embed():
    embed = discord.Embed(
        title="⌨️ Fjord Cartel • Commands & Quick Help",
        description="Quick examples for chat lookups. Use the dashboard menu for the full crafting tools.",
        color=COLOR,
    )
    embed.add_field(
        name="💬 Chat lookups (start with !)",
        value=(
            "`!how to make [item]` — find a recipe and its ingredients.\n"

            "`!where is [ingredient or tool] used` — find ingredient uses and non-consumed tool requirements.\n"
            "`!how much [recipe] can I make with 500 [ingredient]` — estimate batches from the stock you list.\n"
            "`!what does [usable item] do` — search the saved Usable Items page.\n"
            "`!how do I do [activity]` — search saved activity and location notes.\n"
            "`!what tables are related to [topic]` — find matching crafting tables.\n"
            "`!what can I craft: Item x10, Item x5` — check what your stock can make.\n"
            "`/item [item name]` — connect shop prices, crafting outputs, ingredient uses, and required tools.\n"
            "`/search [term]` — search recipes, tables, ingredients, and tools."
        ),
        inline=False,
    )
    embed.add_field(
        name="💰 Shop prices",
        value=(
            "`!how much is [item]` — find its unit price and shop.\n"
            "`!where do I buy [item]` — find where it is sold.\n"
            "`!how much would 500 [item] cost` — calculate a quantity total."
        ),
        inline=False,
    )
    embed.add_field(
        name="📚 Dashboard tools",
        value=(
            "**/dashboard** — open the main menu.\n"
            "**/crafting** — open recipes. **/shops** — browse prices.\n"
            "**/locations** — browse postal codes. **/moonshine** — Old Man selling information.\n"
            "The dashboard also includes Usable Items and the full crafting tools."
        ),
        inline=False,
    )
    embed.add_field(
        name="✍️ Search tips",
        value="Use the item's name or a few key words. Small spelling mistakes are supported. If a result looks wrong or is missing, report it through the Crafting menu.",
        inline=False,
    )
    embed.set_footer(text="FJORD CARTEL • QUICK REFERENCE")
    return embed


class InformationPagerView(SafeView):
    def __init__(self, owner_id: int, source_embed: discord.Embed, page_size: int = 3):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.source_embed = source_embed
        self.page_size = page_size
        self.page = 0
        self.total_pages = max(1, (len(source_embed.fields) + page_size - 1) // page_size)
        self.previous_button.disabled = True
        self.next_button.disabled = self.total_pages <= 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This private directory belongs to someone else. Run /dashboard to open your own.", ephemeral=True)
            return False
        return True

    def current_embed(self) -> discord.Embed:
        embed = discord.Embed.from_dict(self.source_embed.to_dict())
        embed.clear_fields()
        start = self.page * self.page_size
        for field in self.source_embed.fields[start:start + self.page_size]:
            embed.add_field(name=field.name, value=field.value, inline=field.inline)
        embed.set_footer(text=f"FJORD CARTEL • PAGE {self.page + 1}/{self.total_pages} • Use buttons to browse")
        return embed

    async def refresh(self, interaction: discord.Interaction):
        self.previous_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= self.total_pages - 1
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    @discord.ui.button(label="Previous", emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        await self.refresh(interaction)

    @discord.ui.button(label="Next", emoji="➡️", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.total_pages - 1, self.page + 1)
        await self.refresh(interaction)

class DashboardMenuView(SafeView):
    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        select = discord.ui.Select(
            placeholder="Choose a Fjord Cartel section...",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="Crafting", value="crafting", description="Recipes, tables, ingredients, and planning tools", emoji="📚"),
                discord.SelectOption(label="Commands & Help", value="commands", description="Chat commands and examples", emoji="⌨️"),
                discord.SelectOption(label="Shops & Prices", value="shops", description="Browse shop items and prices", emoji="🛒"),
                discord.SelectOption(label="Locations", value="locations", description="Browse postal locations a few at a time", emoji="📍"),
                discord.SelectOption(label="Usable Items", value="usable", description="Inventory items and their requirements", emoji="🎒"),
            ],
        )
        select.callback = self.choose_section
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This private dashboard belongs to someone else. Run /dashboard to open your own.", ephemeral=True)
            return False
        return True

    async def choose_section(self, interaction: discord.Interaction):
        section = interaction.data["values"][0]
        if section == "crafting":
            if bot.recipe_data is None:
                await interaction.response.send_message("The crafting directory is still loading. Try again shortly.", ephemeral=True)
                return
            record_usage("open")
            await interaction.response.edit_message(
                embed=help_embed(),
                view=MainMenuView(interaction.user.id),
            )
            return
        embed_factories = {
            "commands": (commands_embed, 4),
            "shops": (shops_embed, 2),
            "locations": (locations_embed, 3),
            "usable": (usable_embed, 2),
        }
        selected = embed_factories.get(section)
        if selected is None:
            await interaction.response.send_message("That dashboard section could not be found.", ephemeral=True)
            return
        embed_factory, page_size = selected
        source_embed = embed_factory()
        pager = InformationPagerView(interaction.user.id, source_embed, page_size)
        await interaction.response.edit_message(embed=pager.current_embed(), view=pager)


@bot.tree.command(name="crafting", description="Open crafting recipes and tools.")
async def crafting_command(interaction: discord.Interaction):
    if bot.recipe_data is None:
        await interaction.response.send_message("The crafting directory is still loading. Try again shortly.", ephemeral=True)
        return
    record_usage("open")
    await interaction.response.send_message(
        embed=help_embed(),
        view=MainMenuView(interaction.user.id),
        ephemeral=True,
    )


class RecipeSearchResultsView(SafeView):
    def __init__(self, owner_id: int, query: str, results: list[tuple[str, dict]]):
        super().__init__(timeout=300)
        self.owner_id, self.query, self.results = owner_id, query, results
        self.page = 0
        self.page_size = 5
        self.previous_button.disabled = True
        self.next_button.disabled = len(results) <= self.page_size

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("These private search results belong to someone else. Run /search to make your own search.", ephemeral=True)
            return False
        return True

    def current_embed(self):
        total_pages = max(1, (len(self.results) + self.page_size - 1) // self.page_size)
        start = self.page * self.page_size
        embed = discord.Embed(
            title="🔎 Crafting Directory Search",
            description=f"Search: **{self.query[:120]}**\nFound **{len(self.results)}** matching recipe(s).",
            color=COLOR,
        )
        for table_name, recipe in self.results[start:start + self.page_size]:
            ingredients = ", ".join(f"{name} ×{amount}" for name, amount in recipe.get("ingredients", [])) or "No ingredients recorded"
            value = f"**Ingredients:** {ingredients}"
            if recipe.get("tools"):
                value += "\n**Tools (not consumed):** " + ", ".join(recipe["tools"])
            if recipe.get("notes"):
                value += "\n⚠️ " + " ".join(recipe["notes"])
            embed.add_field(name=f"{recipe.get('name', 'Unknown recipe')} · {table_name}"[:256], value=value[:1024], inline=False)
        embed.set_footer(text=f"Page {self.page + 1}/{total_pages} • Search uses saved in-city recipe data only")
        return embed

    async def refresh(self, interaction):
        total_pages = max(1, (len(self.results) + self.page_size - 1) // self.page_size)
        self.previous_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= total_pages - 1
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    @discord.ui.button(label="Previous", emoji="⬅️", style=discord.ButtonStyle.secondary, row=0)
    async def previous_button(self, interaction, button):
        self.page = max(0, self.page - 1)
        await self.refresh(interaction)

    @discord.ui.button(label="Next", emoji="➡️", style=discord.ButtonStyle.primary, row=0)
    async def next_button(self, interaction, button):
        self.page = min(max(0, (len(self.results) - 1) // self.page_size), self.page + 1)
        await self.refresh(interaction)


@bot.tree.command(name="search", description="Search saved recipes, tables, ingredients, and tools.")
@app_commands.describe(query="A recipe, table, ingredient, or tool name")
async def search_command(interaction: discord.Interaction, query: str):
    data = include_usable_item_recipes(get_guild_recipe_data(interaction.guild_id))
    results = advanced_search(data, query=query)
    if not results:
        record_player_activity(interaction.guild_id, interaction.user.id, "Search with no results", query)
        record_usage("no_result", query)
        await interaction.response.send_message(
            "I couldn't find matching saved recipes. Try an ingredient, tool, recipe, or crafting table name.",
            ephemeral=True,
        )
        return
    record_usage("search", query)
    record_player_activity(interaction.guild_id, interaction.user.id, "Searched recipes", query)
    view = RecipeSearchResultsView(interaction.user.id, query, results)
    await interaction.response.send_message(embed=view.current_embed(), view=view, ephemeral=True)


@bot.tree.command(name="shops", description="Browse shop items and prices.")
async def shops_command(interaction: discord.Interaction):
    record_player_activity(interaction.guild_id, interaction.user.id, "Opened directory", "Shops and prices")
    source_embed = shops_embed()
    pager = InformationPagerView(interaction.user.id, source_embed, 2)
    await interaction.response.send_message(embed=pager.current_embed(), view=pager, ephemeral=True)


@bot.tree.command(name="locations", description="Browse postal codes and hidden locations.")
async def locations_command(interaction: discord.Interaction):
    record_player_activity(interaction.guild_id, interaction.user.id, "Opened directory", "Postal locations")
    source_embed = locations_embed()
    pager = InformationPagerView(interaction.user.id, source_embed, 3)
    await interaction.response.send_message(embed=pager.current_embed(), view=pager, ephemeral=True)


@bot.tree.command(name="moonshine", description="Show where to sell Moonshine.")
async def moonshine_command(interaction: discord.Interaction):
    record_player_activity(interaction.guild_id, interaction.user.id, "Opened directory", "Moonshine selling information")
    embed = discord.Embed(
        title="🥃 Fjord Cartel • Moonshine",
        description=(
            "**Sell Moonshine to the Old Man.**\n\n"
            "• The Old Man's location rotates.\n"
            "• His current location is marked on the map.\n"
            "• Find him at the marked location to sell your Moonshine."
        ),
        color=COLOR,
    )
    embed.set_footer(text="FJORD CARTEL • MOONSHINE INFORMATION")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="dashboard", description="Open the Fjord Cartel Information dashboard.")
async def dashboard_command(interaction: discord.Interaction):
    record_player_activity(interaction.guild_id, interaction.user.id, "Opened dashboard")
    await interaction.response.send_message(
        embed=dashboard_embed(),
        view=DashboardMenuView(interaction.user.id),
        ephemeral=True,
    )


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    logger.error("Slash command failed: %s", error, exc_info=(type(error), error, error.__traceback__))
    if interaction.response.is_done():
        await interaction.followup.send("The command could not complete. The error has been logged for troubleshooting.", ephemeral=True)
    else:
        await interaction.response.send_message("The command could not complete. The error has been logged for troubleshooting.", ephemeral=True)


if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise ValueError("DISCORD_BOT_TOKEN is required. Check the Discloud deployment environment.")
    bot.run(token)