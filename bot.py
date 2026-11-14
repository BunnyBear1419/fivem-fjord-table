import hashlib
import io
import json
import logging
import os
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
    OVERRIDE_FILE, CraftingDirectoryView, create_backup, load_recipe_data,
    parse_ingredients, save_recipe_data, search_embed, ingredient_usage_embed,
    build_ingredient_directory, ingredient_directory_embed, ingredient_directory_document,
)
from storage import atomic_write_json, read_json as storage_read_json, file_lock
from enhancements import (
    calculate_recipe_ingredients, recipe_shopping_embed, table_comparison_embed,
    validate_recipe_data, validation_embed, recipes_csv_bytes, recipes_xlsx_bytes,
    ensure_stable_ids, dependency_chain, dependency_lines, inventory_plan,
    multi_recipe_plan, advanced_search, recipe_comparison, merge_recipe_import,
    analytics_embed, chat_recipe_search,
)

PROJECT_NAME = "FiveM Crafting Directory"
BASE_DIR = Path(__file__).resolve().parent
STATS_FILE = BASE_DIR / "stats.json"
REPORTS_FILE = BASE_DIR / "reports.json"
HISTORY_FILE = BASE_DIR / "history.json"
PERMISSIONS_FILE = BASE_DIR / "permissions.json"
LOG_FILE = BASE_DIR / "bot.log"
COLOR = discord.Color.from_rgb(57, 75, 111)

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
        stats = read_json(STATS_FILE, {"commands": 0, "searches": 0, "terms": {}, "tables": {}})
        stats["commands"] = int(stats.get("commands", 0)) + 1
        if kind == "search":
            stats["searches"] = int(stats.get("searches", 0)) + 1
            if term:
                terms = stats.setdefault("terms", {})
                terms[term[:60]] = int(terms.get(term[:60], 0)) + 1
                if len(terms) > 100:
                    stats["terms"] = dict(sorted(terms.items(), key=lambda item: item[1], reverse=True)[:100])
        write_json(STATS_FILE, stats)


def record_table_usage(table_name: str):
    with file_lock():
        stats = read_json(STATS_FILE, {"commands": 0, "searches": 0, "terms": {}, "tables": {}})
        tables = stats.setdefault("tables", {})
        tables[table_name[:100]] = int(tables.get(table_name[:100], 0)) + 1
        if len(tables) > 50:
            stats["tables"] = dict(sorted(tables.items(), key=lambda item: item[1], reverse=True)[:50])
        write_json(STATS_FILE, stats)


def record_recipe_change(before_data: dict, action: str, actor_id: int, summary: str):
    """Keep the latest 30 reversible snapshots to bound runtime storage."""
    with file_lock():
        history = read_json(HISTORY_FILE, [])
        entry_id = max((int(item.get("id", 0)) for item in history), default=0) + 1
        history.append({
            "id": entry_id,
            "action": action,
            "actor_id": actor_id,
            "summary": summary[:300],
            "created_at": discord.utils.utcnow().isoformat(),
            "snapshot": before_data,
        })
        write_json(HISTORY_FILE, history[-30:])
        return entry_id


def is_guild_admin(interaction: discord.Interaction) -> bool:
    return bool(interaction.guild and interaction.user.guild_permissions.manage_guild)


def can_manage_crafting(interaction: discord.Interaction) -> bool:
    if is_guild_admin(interaction):
        return True
    if not interaction.guild:
        return False
    config = read_json(PERMISSIONS_FILE, {"role_ids": []})
    allowed = {int(value) for value in config.get("role_ids", []) if str(value).isdigit()}
    return any(role.id in allowed for role in getattr(interaction.user, "roles", []))


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
        title="📘 FiveM Crafting Directory",
        description="Everything is controlled from this private menu. Choose an option below to get started.",
        color=COLOR,
    )
    embed.add_field(name="Browse recipes", value="Choose a crafting table, then a recipe to view ingredients and tools.", inline=False)
    embed.add_field(name="Search", value="Find recipes by name, ingredient, tool, or table.", inline=False)
    embed.add_field(name="Find ingredient across tables", value="Enter an exact ingredient name to see where it is crafted, which ingredients make it, and every table/recipe that uses it. Similar spellings remain separate.", inline=False)
    embed.add_field(name="All ingredients", value="Browse the complete ingredient directory by name, table, recipe, and quantity. Download the full plain-text list.", inline=False)
    embed.add_field(name="Recipe shopping list", value="Choose a recipe and batch count to calculate the total ingredients needed.", inline=False)
    embed.add_field(name="Crafting table comparison", value="Compare shared ingredients and ingredients unique to each table.", inline=False)
    embed.add_field(name="Production chains", value="Trace an item's crafting dependencies back to base ingredients.", inline=False)
    embed.add_field(name="Inventory calculator", value="Use current stock to calculate craftable batches and missing items.", inline=False)
    embed.add_field(name="Multi-recipe planner", value="Combine several recipes into one shopping list.", inline=False)
    embed.add_field(name="Advanced search", value="Filter by table, ingredient, tool, keyword, and ingredient count.", inline=False)
    embed.add_field(name="Item database", value="Open an item page showing where it is made and used.", inline=False)
    embed.add_field(name="Recipe comparison", value="Compare two recipes and their shared/exclusive ingredients.", inline=False)
    embed.add_field(name="Report an issue", value="Privately report a missing or incorrect entry with table and recipe details.", inline=False)
    embed.add_field(name="Admin tools", value="Manage tables and recipes, exports, backups, reports, and statistics. Manage Server or approved staff role required.", inline=False)
    embed.set_footer(text="Private menu • Only you can see and use this session")
    return embed


class SafeView(discord.ui.View):
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
        # Syncing the one-command local tree replaces the old global command set.
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
        await interaction.response.send_message(embed=search_embed(bot.recipe_data, term, self.table.value.strip() or None), ephemeral=True)


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
            embed=ingredient_usage_embed(bot.recipe_data, ingredient),
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
        if not can_manage_crafting(interaction):
            await interaction.response.send_message("You need Manage Server permission or an approved crafting staff role.", ephemeral=True)
            return

        data = ensure_stable_ids(load_recipe_data())
        before_data = json.loads(json.dumps(data, ensure_ascii=False))
        if self.action == "add_table":
            name = self.table_name.value.strip()
            if not name or any(t["name"].casefold() == name.casefold() for t in data["tables"]):
                await interaction.response.send_message("Enter a unique table name.", ephemeral=True)
                return
            data["tables"].append({"id": __import__("uuid").uuid4().hex, "name": name, "recipes": []})
            record_recipe_change(before_data, "add_table", interaction.user.id, f"Added table: {name}")
            save_recipe_data(data)
            refresh_recipe_data()
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
            record_recipe_change(before_data, "add_recipe", interaction.user.id, f"Added {name} to {table['name']}")
            save_recipe_data(data)
            refresh_recipe_data()
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
            record_recipe_change(before_data, "edit_recipe", interaction.user.id, f"Edited {recipe['name']} in {table['name']}")
            save_recipe_data(data)
            refresh_recipe_data()
            await interaction.response.send_message(f"Updated **{recipe['name']}**. An automatic backup and change-history entry were created.", ephemeral=True)
            return

        if self.action == "remove_recipe":
            table = next((t for t in data["tables"] if t["name"].casefold() == self.table_name.value.strip().casefold()), None)
            index = next((i for i, r in enumerate(table["recipes"]) if r["name"].casefold() == self.recipe_name.value.strip().casefold()), None) if table else None
            if index is None:
                await interaction.response.send_message("Recipe not found in that table.", ephemeral=True)
                return
            removed = table["recipes"].pop(index)
            record_recipe_change(before_data, "remove_recipe", interaction.user.id, f"Removed {removed['name']} from {table['name']}")
            save_recipe_data(data)
            refresh_recipe_data()
            await interaction.response.send_message(f"Removed **{removed['name']}**. An automatic backup and change-history entry were created.", ephemeral=True)
            return

        if self.action == "restore_history":
            try:
                history_id = int(self.history_id.value.strip())
            except ValueError:
                await interaction.response.send_message("Enter a valid history entry number.", ephemeral=True)
                return
            history = read_json(HISTORY_FILE, [])
            entry = next((item for item in history if int(item.get("id", 0)) == history_id), None)
            if not entry or not isinstance(entry.get("snapshot"), dict):
                await interaction.response.send_message("That history entry has no restorable snapshot.", ephemeral=True)
                return
            record_recipe_change(data, "restore", interaction.user.id, f"Restored before history entry #{history_id}")
            save_recipe_data(entry["snapshot"])
            refresh_recipe_data()
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


class AdminMenuView(SafeView):
    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        options = [
            discord.SelectOption(label="Import / merge recipe JSON", value="import_json", emoji="📥"),
            discord.SelectOption(label="Configure staff roles", value="set_roles", emoji="👥"),
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
            discord.SelectOption(label="Validate recipe data", value="validate", emoji="🧪"),
            discord.SelectOption(label="View change history", value="history", emoji="🕘"),
            discord.SelectOption(label="Restore a previous version", value="restore_history", emoji="↩️"),
            discord.SelectOption(label="View directory statistics", value="stats", emoji="📊"),
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
        if not can_manage_crafting(interaction):
            await interaction.response.send_message("You need Manage Server permission or an approved crafting staff role.", ephemeral=True)
            return False
        return True

    async def choose_action(self, interaction: discord.Interaction):
        action = interaction.data["values"][0]
        if action == "back":
            await interaction.response.edit_message(embed=help_embed(), view=MainMenuView(self.owner_id, can_manage_crafting(interaction)))
        elif action in {"add_table", "add_recipe", "edit_recipe", "remove_recipe", "resolve_report", "restore_history"}:
            await interaction.response.send_modal(AdminActionModal(action))
        elif action == "import_json":
            if not is_guild_admin(interaction):
                await interaction.response.send_message("Only Manage Server members can import data.", ephemeral=True)
                return
            await interaction.response.send_modal(ImportRecipeModal())
        elif action == "set_roles":
            if not is_guild_admin(interaction):
                await interaction.response.send_message("Only Manage Server members can configure roles.", ephemeral=True)
                return
            await interaction.response.send_modal(StaffRolesModal())
        elif action == "analytics":
            await interaction.response.send_message(embed=analytics_embed(load_recipe_data(), read_json(STATS_FILE, {})), ephemeral=True)
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
            payload = json.dumps(load_recipe_data(), ensure_ascii=False, indent=2).encode("utf-8")
            await interaction.response.send_message("Current recipe directory export:", file=discord.File(io.BytesIO(payload), filename="crafting-recipes-export.json"), ephemeral=True)
        elif action == "export_csv":
            payload = recipes_csv_bytes(load_recipe_data())
            await interaction.response.send_message("Complete ingredient occurrence export (duplicate entries are preserved):", file=discord.File(io.BytesIO(payload), filename="fivem-crafting-ingredients.csv"), ephemeral=True)
        elif action == "export_xlsx":
            payload = recipes_xlsx_bytes(load_recipe_data())
            await interaction.response.send_message("Excel workbook with all ingredient occurrences:", file=discord.File(io.BytesIO(payload), filename="fivem-crafting-directory.xlsx"), ephemeral=True)
        elif action == "validate":
            findings = validate_recipe_data(load_recipe_data())
            await interaction.response.send_message(embed=validation_embed(findings), ephemeral=True)
        elif action == "history":
            history = read_json(HISTORY_FILE, [])
            if not history:
                await interaction.response.send_message("No recipe changes have been recorded yet. Future admin edits will appear here.", ephemeral=True)
                return
            embed = discord.Embed(title="🕘 Recipe Change History", description=f"Showing the latest {min(10, len(history))} change(s). Use Restore a previous version with an entry number to roll back.", color=COLOR)
            for item in reversed(history[-10:]):
                embed.add_field(name=f"#{item['id']} · {item.get('action', 'change')}", value=f"{item.get('summary', '')}\nBy user ID: {item.get('actor_id', 'unknown')}\n{item.get('created_at', 'unknown')}", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        elif action == "stats":
            data = load_recipe_data()
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
            result = calculate_recipe_ingredients(bot.recipe_data, self.table.value, self.recipe.value, batch_count)
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


class MainMenuView(SafeView):
    def __init__(self, owner_id: int, admin: bool):
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
            discord.SelectOption(label="Inventory calculator", value="inventory", description="Calculate batches from current stock", emoji="🎒"),
            discord.SelectOption(label="Multi-recipe planner", value="multi_plan", description="Combine several recipes into one list", emoji="🧾"),
            discord.SelectOption(label="Advanced search", value="advanced_search", description="Filter recipes by multiple criteria", emoji="🧰"),
            discord.SelectOption(label="Item database", value="item_page", description="Open an item's production and usage page", emoji="📖"),
            discord.SelectOption(label="Recipe comparison", value="recipe_compare", description="Compare two recipes", emoji="⚖️"),
            discord.SelectOption(label="Help and instructions", value="help", description="How to use the crafting directory", emoji="📘"),
            discord.SelectOption(label="Report a recipe issue", value="report", description="Privately report missing or incorrect data", emoji="📨"),
        ]
        if admin:
            options.append(discord.SelectOption(label="Admin tools", value="admin", description="Manage recipes, backups, exports, and reports", emoji="⚙️"))
        select = discord.ui.Select(placeholder="What would you like to do?", options=options)
        select.callback = self.choose_action
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This private menu belongs to someone else. Run /crafting to open your own.", ephemeral=True)
            return False
        return True

    async def choose_action(self, interaction: discord.Interaction):
        action = interaction.data["values"][0]
        if action == "browse":
            view = CraftingDirectoryView(self.owner_id, bot.recipe_data, on_table_selected=record_table_usage)
            await interaction.response.edit_message(embed=view.current_embed(), view=view)
        elif action == "search":
            await interaction.response.send_modal(SearchModal())
        elif action == "ingredient_lookup":
            await interaction.response.send_modal(IngredientLookupModal())
        elif action == "all_ingredients":
            view = IngredientDirectoryView(self.owner_id, bot.recipe_data)
            await interaction.response.edit_message(
                embed=ingredient_directory_embed(bot.recipe_data, 0, view.page_size),
                view=view,
            )
        elif action == "shopping_list":
            await interaction.response.send_modal(RecipeCalculatorModal())
        elif action == "compare_tables":
            await interaction.response.edit_message(embed=table_comparison_embed(bot.recipe_data), view=self)
        elif action == "dependency":
            await interaction.response.send_modal(DependencyModal())
        elif action == "inventory":
            await interaction.response.send_modal(InventoryModal())
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
            if not can_manage_crafting(interaction):
                await interaction.response.send_message("You need Manage Server permission or an approved crafting staff role.", ephemeral=True)
                return
            embed = discord.Embed(title="⚙️ Crafting Admin Tools", description="Choose an action below. Changes automatically create a backup before saving.", color=COLOR)
            await interaction.response.edit_message(embed=embed, view=AdminMenuView(self.owner_id))



class DependencyModal(SafeModal, title="Trace a production chain"):
    item = discord.ui.TextInput(label="Item / recipe output name", max_length=100)
    async def on_submit(self, interaction):
        lines = dependency_lines(dependency_chain(bot.recipe_data, self.item.value.strip()))
        embed = discord.Embed(title="Production chain: " + self.item.value.strip()[:180], description="\n".join(lines)[:3900], color=COLOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class InventoryModal(SafeModal, title="Inventory calculator"):
    table = discord.ui.TextInput(label="Exact crafting table", max_length=100)
    recipe = discord.ui.TextInput(label="Exact recipe name", max_length=100)
    batches = discord.ui.TextInput(label="Target batches", default="1", max_length=3)
    inventory = discord.ui.TextInput(label="Current stock: Item x5, Item x10", style=discord.TextStyle.paragraph, max_length=1500)
    async def on_submit(self, interaction):
        try:
            result = inventory_plan(bot.recipe_data, self.table.value, self.recipe.value, int(self.batches.value.strip()), self.inventory.value)
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
            result = multi_recipe_plan(bot.recipe_data, parsed)
        except (ValueError, TypeError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        embed = discord.Embed(title="Combined production plan", description="\n".join(result["selected"][:8])[:900], color=COLOR)
        ingredient_lines = ["- " + str(n) + " x" + str(q) for n,q in result["ingredients"].items()]
        embed.add_field(name="Combined ingredient totals", value="\n".join(ingredient_lines[:12])[:900] or "None", inline=False)
        if result["tools"]:
            embed.add_field(name="Tools (not consumed)", value=", ".join(result["tools"])[:700], inline=False)
        full_text = "COMBINED PRODUCTION PLAN\n\nRecipes:\n" + "\n".join(result["selected"]) + "\n\nIngredients:\n" + "\n".join(ingredient_lines) + "\n\nTools (not consumed):\n" + ", ".join(result["tools"])
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
            results = advanced_search(bot.recipe_data, self.keyword.value.strip(), self.table.value.strip(), self.ingredient.value.strip(), self.tool.value.strip(), int(self.minimum.value.strip()))
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        embed = discord.Embed(title="Advanced search results", description="Found " + str(len(results)) + " recipe(s).", color=COLOR)
        for table, recipe in results[:5]:
            summary = ", ".join(str(n) + " x" + str(q) for n,q in recipe.get("ingredients", []))
            embed.add_field(name=(recipe.get("name", "Unnamed") + " - " + table)[:256], value=summary[:650] or "No ingredients", inline=False)
        if len(results) > 5:
            embed.set_footer(text=f"Showing 5 of {len(results)} results. Narrow the filters to see fewer matches.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ItemPageModal(SafeModal, title="Item database page"):
    item = discord.ui.TextInput(label="Exact item / ingredient name", max_length=100)
    async def on_submit(self, interaction):
        await interaction.response.send_message(embed=ingredient_usage_embed(bot.recipe_data, self.item.value.strip()), ephemeral=True)


class RecipeCompareModal(SafeModal, title="Compare two recipes"):
    table_a = discord.ui.TextInput(label="First crafting table", max_length=100)
    recipe_a = discord.ui.TextInput(label="First recipe", max_length=100)
    table_b = discord.ui.TextInput(label="Second crafting table", max_length=100)
    recipe_b = discord.ui.TextInput(label="Second recipe", max_length=100)
    async def on_submit(self, interaction):
        try:
            result = recipe_comparison(bot.recipe_data, self.table_a.value, self.recipe_a.value, self.table_b.value, self.recipe_b.value)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        embed = discord.Embed(title="Recipe comparison", description="A: " + result["a"]["recipe"] + " / " + result["a"]["table"] + "\nB: " + result["b"]["recipe"] + " / " + result["b"]["table"], color=COLOR)
        embed.add_field(name="Shared ingredients", value=", ".join(result["shared"]) or "None", inline=False)
        embed.add_field(name="Only in A", value=", ".join(result["only_a"]) or "None", inline=False)
        embed.add_field(name="Only in B", value=", ".join(result["only_b"]) or "None", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)



class StaffRolesModal(SafeModal, title="Configure crafting staff roles"):
    role_ids = discord.ui.TextInput(label="Allowed role IDs (comma-separated)", required=False, max_length=1000)
    async def on_submit(self, interaction):
        if not is_guild_admin(interaction):
            await interaction.response.send_message("Only Manage Server members can configure staff roles.", ephemeral=True)
            return
        values = []
        for raw in self.role_ids.value.split(","):
            raw = raw.strip()
            if raw and not raw.isdigit():
                await interaction.response.send_message("Role IDs must be numeric and separated by commas.", ephemeral=True)
                return
            if raw:
                values.append(int(raw))
        write_json(PERMISSIONS_FILE, {"role_ids": sorted(set(values))})
        await interaction.response.send_message("Saved " + str(len(set(values))) + " approved crafting staff role(s).", ephemeral=True)


class ImportRecipeModal(SafeModal, title="Import / merge recipe JSON"):
    json_text = discord.ui.TextInput(label="Paste JSON with a top-level tables list", style=discord.TextStyle.paragraph, max_length=4000)
    mode = discord.ui.TextInput(label="Name conflicts: skip or replace", default="skip", max_length=10)
    async def on_submit(self, interaction):
        if not is_guild_admin(interaction):
            await interaction.response.send_message("Only Manage Server members can import recipe data.", ephemeral=True)
            return
        try:
            incoming = json.loads(self.json_text.value)
            mode = self.mode.value.strip().casefold()
            if mode not in {"skip", "replace"}:
                raise ValueError("Conflict mode must be skip or replace.")
            current = ensure_stable_ids(load_recipe_data())
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
        if interaction.user.id != self.owner_id or not is_guild_admin(interaction):
            await interaction.response.send_message("Only the importing Manage Server member can confirm.", ephemeral=True)
            return False
        return True
    @discord.ui.button(label="Confirm import", style=discord.ButtonStyle.success)
    async def confirm(self, interaction, button):
        current = ensure_stable_ids(load_recipe_data())
        if recipe_fingerprint(current) != self.base_fingerprint:
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(content="The recipe data changed after this preview was created. Nothing was imported. Reopen the import tool and create a fresh preview.", embed=None, view=self)
            return
        record_recipe_change(current, "import_merge", interaction.user.id, "Imported " + str(self.summary["recipes_added"]) + " recipes")
        save_recipe_data(ensure_stable_ids(self.merged))
        refresh_recipe_data()
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
    """Answer natural-language ! lookups using only the saved FiveM recipe directory."""
    if message.author.bot:
        return
    content = (message.content or "").strip()
    if not content.startswith("!"):
        await bot.process_commands(message)
        return
    query = content[1:].strip()
    if not query:
        await message.reply("Try `!how to make [item]` or `!where is [ingredient] used`.", mention_author=False)
        return
    if query.casefold() in {"help", "crafting"}:
        await bot.process_commands(message)
        return
    if bot.recipe_data is None:
        await message.reply("The crafting directory is still loading. Try again shortly.", mention_author=False)
        return

    matches = chat_recipe_search(bot.recipe_data, query, limit=3)
    if not matches:
        await message.reply(
            f"I couldn't find a close match for **{query[:100]}**. Try the exact item name or use `/crafting` to browse.",
            mention_author=False,
        )
        return

    embed = discord.Embed(
        title=f"Crafting lookup: {query[:180]}",
        description="Matches are taken directly from the server's FiveM crafting directory. Ingredient names and quantities are shown as recorded.",
        color=COLOR,
    )
    for match in matches:
        ingredient_lines = [
            f"• **{name}** ×{quantity}"
            for name, quantity in match.get("ingredients", [])
        ]
        value = "**Table:** " + match["table"] + "\\n"
        value += "**Recipe:** " + match["recipe"] + "\\n"
        value += "**Ingredients:**\\n" + ("\\n".join(ingredient_lines) if ingredient_lines else "None recorded")
        if match.get("tools"):
            value += "\\n**Tools (not consumed):** " + ", ".join(match["tools"])
        embed.add_field(name=match.get("match_label", "Closest match")[:256], value=value[:1024], inline=False)
    embed.set_footer(text="Game reference only • Use /crafting for the full directory")
    await message.reply(embed=embed, mention_author=False)


@bot.tree.command(name="crafting", description="Open the private FiveM crafting menu.")
async def crafting_command(interaction: discord.Interaction):
    if bot.recipe_data is None:
        await interaction.response.send_message("The crafting directory is still loading. Try again shortly.", ephemeral=True)
        return
    record_usage("open")
    await interaction.response.send_message(
        embed=help_embed(),
        view=MainMenuView(interaction.user.id, can_manage_crafting(interaction)),
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
