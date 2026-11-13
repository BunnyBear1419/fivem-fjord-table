# FiveM Crafting Directory Discord Bot

A Discord bot that provides a private, interactive reference for crafting tables and recipes used in FiveM roleplay servers.

## One slash command

Members use only **`/crafting`**. It opens a private dropdown menu with:

- **Browse recipes** — choose a crafting table, then a recipe to view ingredients and tools.
- **Search recipes** — search by recipe name, ingredient, tool, or optional table filter.
- **Find ingredient across tables** — locate an exact ingredient, where it is produced, and where it is consumed.
- **All ingredients** — browse or download the complete exact-name ingredient directory.
- **Recipe shopping list** — calculate required ingredients for 1–999 batches; repeated ingredient rows are summed for the requested total.
- **Crafting table comparison** — compare shared and table-exclusive ingredients.
- **Help and instructions** — see how to use the directory.
- **Report a recipe issue** — submit an issue type, optional table/recipe, and details.
- **Admin tools** — shown only to members with Manage Server permission.

## Admin menu

The Admin tools submenu includes:

- Add a crafting table.
- Add, edit, or remove a recipe.
- Create a manual backup.
- Export JSON, CSV, and Excel workbooks (each ingredient occurrence is a separate row).
- Validate recipe data for missing names/ingredients, invalid quantities, repeated recipe names, and possible spelling variations. Findings are review-only; nothing is auto-corrected.
- View a reversible recipe change history and restore a prior snapshot.
- View table and recipe totals.
- Review structured issue reports and resolve a report by number.

Admin actions check the Manage Server permission again when submitted. Every recipe-data change creates a timestamped backup and a history snapshot before saving.

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
- `enhancements.py` — shopping-list calculations, table comparisons, validation, and CSV/Excel exports.
- `history.json` — reversible administrator change snapshots, created when the first change is made.
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
