# FiveM Crafting Directory Discord Bot

A Discord bot that provides a private, interactive reference for crafting tables and recipes used in FiveM roleplay servers.

## Member commands

- `/crafting` — opens a private interactive crafting directory.
- `/crafting search:<term>` — searches recipe names, table names, ingredients, and tools from the main command.
- `/crafting-search query:<term> table:<optional>` — advanced search with an optional crafting-table filter.
- `/crafting-help` — displays the command guide.
- `/crafting-stats` — displays aggregate command/search totals and the most-used search terms and tables.
- `/crafting-report details:<text>` — privately submits a missing or incorrect recipe report.

The private directory uses dropdowns to choose a crafting table and recipe. It displays ingredients and quantities separately from reusable tools. Menus are locked to the person who opened them.

## Administrator commands

The `/crafting-admin` command group is restricted to members with the Discord **Manage Server** permission.

- `/crafting-admin add-table` — create a crafting table.
- `/crafting-admin add-recipe` — add a recipe to a table.
- `/crafting-admin edit-recipe` — change a recipe name, ingredients, or tools.
- `/crafting-admin remove-recipe` — remove a recipe.
- `/crafting-admin backup` — create a manual JSON backup.
- `/crafting-admin export` — download the current recipe directory as JSON.
- `/crafting-admin stats` — view table and recipe totals.
- `/crafting-admin reports` — review the latest open recipe reports.
- `/crafting-admin resolve-report` — mark a report as resolved.

For ingredient input, use comma-separated entries such as `Plastic bag x2, Powder x1`. Repeated ingredient entries are intentionally preserved and never deduplicated.

Every administrator recipe edit creates a timestamped backup before saving. Admin edits are written to `crafting-data.json`, a runtime override separate from the source `recipes.json`. Use `/crafting-admin export` after making changes and keep the exported file somewhere safe; runtime files and backups are stored on the Discloud app filesystem and should not be treated as your only copy.

## Logging and privacy

- Errors are written to the Discloud console and `bot.log`.
- Usage statistics store aggregate counts and popular search terms/table selections, not full message histories.
- Recipe reports are private to the submitter and can be reviewed by server administrators.
- Search, help, stats, and report replies are ephemeral (visible only to the person who invoked them).

## Recipe data

- `recipes.json` — original bundled crafting table and recipe data.
- `crafting-data.json` — runtime admin-edited override, created after the first admin change.
- `crafting.py` — directory UI, search, ingredient parsing, and backup/storage helpers.
- `bot.py` — Discord commands, admin controls, usage tracking, reports, and logging.

The initial Glovebox Table data was transcribed from the in-game screenshots supplied for this project. OCR-derived entries from older workbooks should be added only after checking the source screenshots. Always verify recipes against the current server because resource configurations can change.

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

This project is a FiveM roleplay game reference only, not real-world instructions.
