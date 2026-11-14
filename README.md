# FiveM Crafting Directory Discord Bot

A Discord bot that provides a private, interactive reference for crafting tables and recipes used in FiveM roleplay servers.

## Chat lookup shortcut

Members can also type messages such as `!how to make Heroin`, `!how do I craft Kief`, or `!where is Clean Weed Bud used`. The bot searches the existing recipe data, tolerates common spelling mistakes, and offers a dropdown when several close matches are found. The person who asked can select the intended recipe. This is a local directory lookup, not an external AI service; it does not invent recipes or change ingredient names.

**Discord setup required:** In the Discord Developer Portal, open the bot application, go to **Bot → Privileged Gateway Intents**, enable **Message Content Intent**, and save. The bot requests this intent in code. Without the portal toggle, Discord will not provide ordinary message text to the shortcut.

## One slash command

Members use only **`/crafting`**. It opens a private dropdown menu with:

- **Browse recipes** — choose a crafting table, then a recipe to view ingredients and tools. Both table and recipe selectors paginate in groups of 25 to respect Discord's select-menu limits.
- **Search recipes** — search by recipe name, ingredient, tool, or optional table filter.
- **Find ingredient across tables** — locate an exact ingredient, where it is produced, and where it is consumed.
- **All ingredients** — browse or download the complete exact-name ingredient directory.
- **Recipe shopping list** — calculate required ingredients for 1–999 batches; repeated ingredient rows are summed for the requested total.
- **Crafting table comparison** — compare shared and table-exclusive ingredients.
- **Production chains** — trace recipe outputs through nested ingredient recipes to base items (cycle/depth limited).
- **Full production cost planner** — calculate total base ingredients for a target number of finished batches, multiplying quantities through uniquely matched intermediate recipes. If an item has multiple possible producer recipes, it flags the choice instead of guessing. This calculates material requirements, not in-game cash prices.
- **Inventory calculator** — enter current stock once to calculate craftable batches plus missing quantities.
- **My saved inventory** — save your personal ingredient stock privately per Discord server, update or clear it, and reuse it when planning recipes.
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
- View table and recipe totals plus usage analytics, including common searches that return no matches.
- Review spelling and data warnings. Possible spelling variations are suggestions only; ingredient names are never automatically merged or renamed.
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
- Usage statistics store aggregate counts, popular search terms/table selections, and bounded no-result search terms, not full message histories.
- Saved player inventories are separated by server and Discord user ID; they are not shared with other players. They are stored on the Discloud app filesystem, so a host-side rebuild or app replacement may reset runtime data.
- Recipe reports are stored for administrators to review.
- The slash-command directory and saved-inventory menus are ephemeral (visible only to the person who invoked them). Chat lookup replies are posted in the channel where the player asks, and only the original requester can use the match dropdown. Saved player inventories are separated by server and Discord user ID; they are not shared with other players. Inventory data is stored on the Discloud app filesystem and may be lost during a host-side rebuild or app replacement. Large inventory and multi-recipe plans include complete text attachments so Discord embed limits do not cut off the full totals.

## Recipe data

- `recipes.json` — original bundled crafting table and recipe data.
- `crafting-data.json` — runtime admin-edited override, created after the first admin change.
- `crafting.py` — directory UI, search, ingredient parsing, and backup helpers.
- `storage.py` — atomic JSON reads/writes and a process-wide storage lock.
- `enhancements.py` — production chains, inventory and multi-recipe planning, advanced search, comparisons, imports, analytics, validation, typo-tolerant matching, and CSV/Excel exports.
- `inventories.json` — private per-server/per-player saved stock (runtime data).
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


## Additional player and server tools

- **Saved inventory backup:** In `/crafting` → My saved inventory, use Export backup to download a JSON file. Restore backup accepts the JSON contents pasted into the restore modal. Keep exports outside Discloud.
- **Inventory-aware crafting assistant:** In a server channel, use `!what can I craft: Item x10, Other Item x5`. It reports recipes that the supplied stock can craft, based only on the active server recipe directory.
- **Shareable shopping lists:** The recipe shopping list result includes a button to post the calculated list into the current channel.
- **Ingredient aliases:** Manage Server / approved crafting staff → Admin tools → Manage ingredient aliases. Enter one mapping per line, such as `weed => Clean Weed Bud`. Aliases only affect search; saved ingredient and recipe names are not renamed.
- **Staff audit log:** Admin tools → Staff activity audit log shows recent tracked recipe, alias, inventory and profile actions. The log is bounded to the latest 1,000 entries.
- **Health check:** Admin tools → System health check shows bot readiness, directory counts, backup count and runtime file presence.
- **Server recipe profiles:** Admin tools → Create server recipe profile copies the current directory into a profile for that Discord server and activates it. Switch server recipe profile activates another existing profile. Recipe edits and imports are saved to the active profile. Profiles are runtime data and are excluded from Git.
- **Separate server data:** A server without an active profile continues using the shared base recipe directory. Create a profile before making server-specific recipe changes.

### Runtime persistence warning

Discloud runtime JSON files (saved inventories, aliases, audit logs, profile mappings and profile snapshots) are not committed to Git. Download recipe and inventory backups regularly and store them outside the hosting application. A host-side rebuild or app replacement may remove runtime files.
