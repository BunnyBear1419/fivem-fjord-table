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
    OVERRIDE_FILE, CraftingDirectoryView, create_backup, load_recipe_data,
    parse_ingredients, save_recipe_data, search_embed, ingredient_usage_embed,\n    build_ingredient_directory, ingredient_directory_embed, ingredient_directory_document,
)

PROJECT_NAME = "FiveM Crafting Directory"
BASE_DIR = Path(__file__).resolve().parent
STATS_FILE = BASE_DIR / "stats.json"
REPORTS_FILE = BASE_DIR / "reports.json"
LOG_FILE = BASE_DIR / "bot.log"
COLOR = discord.Color.from_rgb(57, 75, 111)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
logger = logging.getLogger("crafting-bot")


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


def help_embed():
    embed = discord.Embed(
        title="📘 FiveM Crafting Directory",
        description="Everything is controlled from this private menu. Choose an option below to get started.",
        color=COLOR,
    )
    embed.add_field(name="Browse recipes", value="Choose a crafting table, then a recipe to view ingredients and tools.", inline=False)
    embed.add_field(name="Search", value="Find recipes by name, ingredient, tool, or table.", inline=False)
    embed.add_field(name="Find ingredient across tables", value="Enter an exact ingredient name to see where it is crafted, which ingredients make it, and every table/recipe that uses it. Similar spellings remain separate.", inline=False)\n    embed.add_field(name="All ingredients", value="Browse the complete ingredient directory by name, table, recipe, and quantity. Download the full plain-text list.", inline=False)
    embed.add_field(name="Report an issue", value="Privately report a missing or incorrect entry.", inline=False)
    embed.add_field(name="Admin tools", value="Manage tables and recipes, exports, backups, reports, and statistics. Manage Server permission required.", inline=False)
    embed.set_footer(text="Private menu • Only you can see and use this session")
    return embed


class CraftingBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.default())
        self.recipe_data = None
        self.guild_commands_cleaned = False

    async def setup_hook(self):
        self.recipe_data = load_recipe_data()
        # Syncing the one-command local tree replaces the old global command set.
        synced = await self.tree.sync()
        count = sum(len(table.get("recipes", [])) for table in self.recipe_data["tables"])
        logger.info("Synced %s global slash command(s). Loaded %s table(s) and %s recipe(s).", len(synced), len(self.recipe_data["tables"]), count)

    async def on_ready(self):
        logger.info("%s online as %s | guilds connected: %s", PROJECT_NAME, self.user, len(self.guilds))
        # Remove any legacy guild-specific copies created by older bot versions.
        if not self.guild_commands_cleaned:
            for guild in self.guilds:
                self.tree.clear_commands(guild=guild)
                await self.tree.sync(guild=guild)
            self.guild_commands_cleaned = True
            logger.info("Cleared legacy guild-specific slash commands.")


bot = CraftingBot()


def refresh_recipe_data():
    bot.recipe_data = load_recipe_data()


class SearchModal(discord.ui.Modal, title="Search crafting recipes"):
    query = discord.ui.TextInput(label="What are you looking for?", placeholder="Recipe, ingredient, tool, or table", max_length=100)
    table = discord.ui.TextInput(label="Limit to a table (optional)", placeholder="Example: Glovebox Table", required=False, max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        term = self.query.value.strip()
        record_usage("search", term)
        await interaction.response.send_message(embed=search_embed(bot.recipe_data, term, self.table.value.strip() or None), ephemeral=True)


class IngredientLookupModal(discord.ui.Modal, title="Find ingredient across tables"):
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


class ReportModal(discord.ui.Modal, title="Report a recipe issue"):
    details = discord.ui.TextInput(label="What needs correcting or adding?", style=discord.TextStyle.paragraph, placeholder="Include the table, recipe name, and what is wrong or missing.", max_length=1500)

    async def on_submit(self, interaction: discord.Interaction):
        reports = read_json(REPORTS_FILE, [])
        report_id = max((int(item.get("id", 0)) for item in reports), default=0) + 1
        reports.append({
            "id": report_id,
            "guild_id": interaction.guild_id,
            "user_id": interaction.user.id,
            "details": self.details.value.strip(),
            "created_at": discord.utils.utcnow().isoformat(),
            "status": "open",
        })
        write_json(REPORTS_FILE, reports)
        logger.info("Recipe report #%s submitted in guild %s", report_id, interaction.guild_id)
        await interaction.response.send_message(f"Your report **#{report_id}** has been saved for server administrators.", ephemeral=True)


class AdminActionModal(discord.ui.Modal):
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
        }
        title, inputs = fields[action]
        super().__init__(title=title)
        for key, label, required, limit in inputs:
            field = discord.ui.TextInput(label=label, required=required, max_length=limit, custom_id=key)
            setattr(self, key, field)
            self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_guild_admin(interaction):
            await interaction.response.send_message("Manage Server permission is required.", ephemeral=True)
            return

        data = load_recipe_data()
        if self.action == "add_table":
            name = self.table_name.value.strip()
            if not name or any(t["name"].casefold() == name.casefold() for t in data["tables"]):
                await interaction.response.send_message("Enter a unique table name.", ephemeral=True)
                return
            data["tables"].append({"name": name, "recipes": []})
            save_recipe_data(data)
            refresh_recipe_data()
            await interaction.response.send_message(f"Added **{name}**. An automatic backup was created.", ephemeral=True)
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
                "name": name, "ingredients": ingredients,
                "tools": [x.strip() for x in self.tools.value.split(",") if x.strip()],
                "review": "Added by server administrator", "source": "CraftingBot admin menu",
            })
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
            save_recipe_data(data)
            refresh_recipe_data()
            await interaction.response.send_message(f"Updated **{recipe['name']}**. An automatic backup was created.", ephemeral=True)
            return

        if self.action == "remove_recipe":
            table = next((t for t in data["tables"] if t["name"].casefold() == self.table_name.value.strip().casefold()), None)
            index = next((i for i, r in enumerate(table["recipes"]) if r["name"].casefold() == self.recipe_name.value.strip().casefold()), None) if table else None
            if index is None:
                await interaction.response.send_message("Recipe not found in that table.", ephemeral=True)
                return
            removed = table["recipes"].pop(index)
            save_recipe_data(data)
            refresh_recipe_data()
            await interaction.response.send_message(f"Removed **{removed['name']}**. An automatic backup was created.", ephemeral=True)
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


class AdminMenuView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        options = [
            discord.SelectOption(label="Add a crafting table", value="add_table", emoji="➕"),
            discord.SelectOption(label="Add a recipe", value="add_recipe", emoji="🧪"),
            discord.SelectOption(label="Edit a recipe", value="edit_recipe", emoji="✏️"),
            discord.SelectOption(label="Remove a recipe", value="remove_recipe", emoji="🗑️"),
            discord.SelectOption(label="Create a backup", value="backup", emoji="💾"),
            discord.SelectOption(label="Export recipe data", value="export", emoji="📤"),
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
        if not is_guild_admin(interaction):
            await interaction.response.send_message("Manage Server permission is required.", ephemeral=True)
            return False
        return True

    async def choose_action(self, interaction: discord.Interaction):
        action = interaction.data["values"][0]
        if action == "back":
            await interaction.response.edit_message(embed=help_embed(), view=MainMenuView(self.owner_id, is_guild_admin(interaction)))
        elif action in {"add_table", "add_recipe", "edit_recipe", "remove_recipe", "resolve_report"}:
            await interaction.response.send_modal(AdminActionModal(action))
        elif action == "backup":
            path = create_backup()
            await interaction.response.send_message(f"Backup created: **{path.name}**", ephemeral=True)
        elif action == "export":
            payload = json.dumps(load_recipe_data(), ensure_ascii=False, indent=2).encode("utf-8")
            await interaction.response.send_message("Current recipe directory export:", file=discord.File(io.BytesIO(payload), filename="crafting-recipes-export.json"), ephemeral=True)
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
            for report in reversed(open_reports):
                embed.add_field(name=f"Report #{report['id']}", value=f"{report.get('details', '')[:700]}\nSubmitted: {report.get('created_at', 'unknown')}", inline=False)
            embed.set_footer(text="Choose Resolve a report in the admin menu when an issue is addressed.")
            await interaction.response.send_message(embed=embed, ephemeral=True)


class IngredientDirectoryView(discord.ui.View):
    def __init__(self, owner_id: int, data: dict):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.data = data
        self.page = 0
        self.page_size = 8
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


class MainMenuView(discord.ui.View):
    def __init__(self, owner_id: int, admin: bool):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        options = [
            discord.SelectOption(label="Browse recipes", value="browse", description="Choose a table and recipe", emoji="📚"),
            discord.SelectOption(label="Search recipes", value="search", description="Search names, ingredients, tools, or tables", emoji="🔎"),
            discord.SelectOption(label="Find ingredient across tables", value="ingredient_lookup", description="See every table and recipe that uses an exact ingredient", emoji="🧩"),\n            discord.SelectOption(label="All ingredients", value="all_ingredients", description="Browse or download the complete ingredient list", emoji="📋"),
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
        elif action == "help":
            await interaction.response.edit_message(embed=help_embed(), view=self)
        elif action == "report":
            await interaction.response.send_modal(ReportModal())
        elif action == "admin":
            if not is_guild_admin(interaction):
                await interaction.response.send_message("Manage Server permission is required.", ephemeral=True)
                return
            embed = discord.Embed(title="⚙️ Crafting Admin Tools", description="Choose an action below. Changes automatically create a backup before saving.", color=COLOR)
            await interaction.response.edit_message(embed=embed, view=AdminMenuView(self.owner_id))


@bot.tree.command(name="crafting", description="Open the private FiveM crafting menu.")
async def crafting_command(interaction: discord.Interaction):
    if bot.recipe_data is None:
        await interaction.response.send_message("The crafting directory is still loading. Try again shortly.", ephemeral=True)
        return
    record_usage("open")
    await interaction.response.send_message(
        embed=help_embed(),
        view=MainMenuView(interaction.user.id, is_guild_admin(interaction)),
        ephemeral=True,
    )


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
