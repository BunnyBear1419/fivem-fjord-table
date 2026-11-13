# FiveM Crafting Directory Discord Bot

A Discord bot that provides a private, interactive reference for crafting tables and recipes used in FiveM roleplay servers.

## One slash command

Members use only **`/crafting`**. It opens a private dropdown menu with:

- **Browse recipes** — choose a crafting table, then a recipe to view ingredients and tools. Both table and recipe selectors paginate in groups of 25 to respect Discord's select-menu limits.
- **Search recipes** — search by recipe name, ingredient, tool, or optional table filter.
- **Find ingredient across tables** — locate an exact ingredient, where it is produced, and where it is consumed.
- **All ingredients** — browse or download the complete exact-name ingredient directory.
- **Recipe shopping list** — calculate required ingredients for 1–999 batches; repeated ingredient rows are summed for the requested total.
- **Crafting table comparison** — compare shared and table-exclusive ingredients.
- **Production chains** — trace recipe outputs through nested ingredient recipes to base items (cycle/depth limited).
- **Inventory calculator** — enter current stock and calculate craftable batches plus missing quantities.
- **Multi-recipe planner** — combine several table/recipe/batch requests into one shopping list.
- **Advanced search** — filter by keyword, table, ingredient, tool, and minimum ingredient-row count.
- **Item database** — open an exact-name item page showing where it is produced and consumed.
- **Recipe comparison** — compare two recipes' shared and exclusive ingredients.
- **Help and instructions** — see how to use the directory.
- **Report a recipe issue** — submit an issue type, optional table/recipe, and details.
- **Admin tools** — shown to members with Manage Server permission or an approved crafting staff role; sensitive role configuration and imports still require Manage Server.

## Admin menu

The Admin tools submenu includes:

- Add a crafting table.
- Add, edit, or remove a recipe.
- Create a manual backup and download the latest backup file for an external copy.
- Export JSON, CSV, and Excel workbooks (each ingredient occurrence is a separate row).
- Validate recipe data for missing names/ingredients, invalid quantities, repeated recipe names, and possible spelling variations. Findings are review-only; nothing is auto-corrected.
- View a reversible recipe change history and restore a prior snapshot.
- View table and recipe totals plus usage analytics.
- Configure approved staff role IDs (Manage Server is required to change role permissions).
- Import/merge recipe JSON (up to the Discord modal's 4,000-character limit) with a preview, structural validation, skip/replace conflict handling, stale-preview protection, backup, and history snapshot.
- Review structured issue reports and resolve a report by number.

Admin actions re-check permissions when submitted. Recipe editing, backup, exports, reports, validation, and history can be granted to approved staff roles; changing staff roles and importing JSON require Manage Server. Every recipe-data change creates a timestamped backup and a history snapshot before saving. Automatic backups run at startup and every 24 hours; up to 25 timestamped backup files are retained. Admins can download the newest backup from the admin menu; keep a copy outside Discloud because host-side rebuilds or app replacement may not preserve local runtime files. The latest 30 reversible history snapshots are retained. Issue reports are capped at 500 and usage analytics retain at most 100 search terms and 50 table counters. Recipe tables and recipes receive stable IDs when data is loaded and saved.

For ingredient input, use comma-separated entries such as `Plastic bag x2, Powder x1`. Repeated ingredient entries are intentionally preserved and never deduplicated.

Admin edits are written to `crafting-data.json`, a runtime override separate from source `recipes.json`. Writes use a same-directory temporary file, flush to disk, and atomically replace the prior JSON file; concurrent in-process writes are serialized. Corrupt JSON is reported and preserved instead of silently replaced with empty defaults. Use the Export option after making changes and keep the exported file somewhere safe; runtime files, staff-role settings, and backups are stored on the Discloud app filesystem. That filesystem may not survive every host-side rebuild or app replacement, so download exports/backups and keep an external copy.

## Old slash commands

The bot now syncs only the single global `/crafting` command. On startup it also clears legacy guild-specific command registrations in servers the bot is connected to. Discord may take up to an hour to remove old global command suggestions from every client; restarting Discord or refreshing the client can help.

Do not delete and reinvite the bot just to refresh commands.

## Logging and privacy

- Errors are written to the Discloud console and rotating `bot.log` files (1 MB per file, 3 rotated files retained).
- Interactive menu, button, select, and modal failures are logged and return a private error message.
- The optional HTTP health endpoint returns HTTP 200 only when the Discord bot is ready, and HTTP 503 while it is starting or unavailable.
- Usage statistics store aggregate counts and popular search terms/table selections, not full message histories.
- Recipe reports are stored for administrators to review.
- The directory and all menus are ephemeral (visible only to the person who invoked them). Large inventory and multi-recipe plans include complete text attachments so Discord embed limits do not cut off the full totals.

## Recipe data

- `recipes.json` — original bundled crafting table and recipe data.
- `crafting-data.json` — runtime admin-edited override, created after the first admin change.
- `crafting.py` — directory UI, search, ingredient parsing, and backup helpers.
- `storage.py` — atomic JSON reads/writes and a process-wide storage lock.
- `enhancements.py` — production chains, inventory and multi-recipe planning, advanced search, comparisons, imports, analytics, validation, and CSV/Excel exports.
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
