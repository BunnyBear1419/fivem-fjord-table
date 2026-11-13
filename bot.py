import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import discord
from discord import app_commands
from discord.ext import commands

from crafting import CraftingDirectoryView, load_recipe_data, search_embed

PROJECT_NAME = "FiveM Crafting Directory"
BOT_INTENTS = discord.Intents.default()


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
        print(f"Keepalive endpoint unavailable: {exc}")


threading.Thread(target=run_web_server, daemon=True).start()


class CraftingBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=BOT_INTENTS)
        self.recipe_data = None

    async def setup_hook(self):
        self.recipe_data = load_recipe_data()
        synced = await self.tree.sync()
        recipe_count = sum(len(table.get("recipes", [])) for table in self.recipe_data["tables"])
        print(f"Registered {len(synced)} slash command(s).")
        print(f"Loaded {len(self.recipe_data['tables'])} table(s) and {recipe_count} recipe(s).")


bot = CraftingBot()


@bot.event
async def on_ready():
    print("=" * 48)
    print(f"{PROJECT_NAME} online as {bot.user}")
    print(f"Guilds connected: {len(bot.guilds)}")
    print("=" * 48)


@bot.tree.command(name="crafting", description="Open your private FiveM crafting directory.")
@app_commands.describe(search="Optional: search by recipe, ingredient, tool, or table name.")
async def crafting_command(interaction: discord.Interaction, search: str | None = None):
    if bot.recipe_data is None:
        await interaction.response.send_message("The crafting directory is still loading. Try again shortly.", ephemeral=True)
        return
    if search and search.strip():
        await interaction.response.send_message(embed=search_embed(bot.recipe_data, search.strip()), ephemeral=True)
        return
    view = CraftingDirectoryView(interaction.user.id, bot.recipe_data)
    await interaction.response.send_message(embed=view.current_embed(), view=view, ephemeral=True)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print(f"Slash command error: {error}")
    if not interaction.response.is_done():
        await interaction.response.send_message("⚠️ The command could not complete. Please try again.", ephemeral=True)


if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise ValueError("DISCORD_BOT_TOKEN is required.")
    bot.run(token)
