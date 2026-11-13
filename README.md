# FiveM Crafting Directory Discord Bot

A Discord bot that provides a private, interactive reference for crafting tables and recipes used in FiveM roleplay servers.

## One slash command

Members use only **`/crafting`**. It opens a private dropdown menu with:

- **Browse recipes** — choose a crafting table, then a recipe to view ingredients and tools.
- **Search recipes** — search by recipe name, ingredient, tool, or optional table filter.
- **Help and instructions** — see how to use the directory.
- **Report a recipe issue** — privately submit a missing or incorrect entry.
- **Admin tools** — shown only to members with Manage Server permission.

## Admin menu

The Admin tools submenu includes:

- Add a crafting table.
- Add, edit, or remove a recipe.
- Create a manual backup.
- Export the current recipe data as JSON.
- View table and recipe totals.
- Review open reports and resolve a report by number.

Admin actions check the Manage Server permission again when submitted. Every recipe-data change creates a timestamped backup before saving.

For ingredient input, use comma-separated entries such as `Plastic bag x2, Powder x1`. Repeated ingredient entries are intentionally preserved and never deduplicated.

Admin edits are written to `crafting-data.json`, a runtime override separate from source `recipes.json`. Use the Export option after making changes and keep the exported file somewhere safe; runtime files and backups are stored on the Discloud app filesystem and should not be treated as your only copy.

## Old slash commands

The bot now syncs only the single global `/crafting` command. On startup it also clears legacy guild-specific command registrations in servers the bot is connected to. Discord may take up to an hour to remove old global command suggestions from every client; restarting Discord or refreshing the client can help.

Do not delete and reinvite the bot just to refresh commands.

## Logging and privacy

- Errors are written to the Discloud console and `bot.log`.
- Usage statistics store aggregate counts and popular search terms/table selections, not full message histories.
- Recipe reports are stored for administrators to review.
- The directory and all menus are ephemeral (visible only to the person who invoked them).

## Recipe data

- `recipes.json` — original bundled crafting table and recipe data.
- `crafting-data.json` — runtime admin-edited override, created after the first admin change.
- `crafting.py` — directory UI, search, ingredient parsing, and backup/storage helpers.
- `bot.py` — the one slash command, dropdown menus, admin controls, usage tracking, reports, and logging.

Always verify recipes against the current server because resource configurations can change.

## Hosting

This repository is configured as a Discloud Discord bot:

- `TYPE=bot`
- `MAIN=bot.py`
- GitHub repository secrets `DISCORD_BOT_TOKEN` and `DISCLOUD_TOKEN` are required by the deployment workflow.
- GitHub Actions deploys only after the test workflow succeeds, or when manually triggered.

## Local run

Install dependencies from `requirements.txt`, set `DISCORD_BOT_TOKEN`, then run:

```bash
python bot.py
```

## Scope

This is a FiveM roleplay game reference only, not real-world instructions.
