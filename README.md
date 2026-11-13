# FiveM Crafting Directory Discord Bot

A Discord bot that provides a private, interactive reference for crafting tables and recipes used in FiveM roleplay servers.

## Discord command

- `/crafting` — opens a private menu visible only to the person who ran the command.
- `/crafting search:<term>` — privately searches recipe names, table names, ingredients, and reusable tools.

The private menu uses Discord dropdowns:
1. Choose a crafting table.
2. Choose a recipe.
3. View required ingredients and quantities.
4. View tools separately; tools are marked as not consumed.

The menu is locked to the user who opened it. Other members cannot operate that user's private menu. Each person can run `/crafting` to open their own.

## Recipe data

- `recipes.json` — crafting table and recipe data.
- `crafting.py` — private Discord menu, recipe embeds, and search.
- `bot.py` — Discord bot entry point.

The initial Glovebox Table data was transcribed from the in-game screenshots supplied for this project. OCR-derived entries from older workbooks will be added only after checking the source screenshots. Always verify recipes against the current server because resource configurations can change.

## Hosting

This repository is configured as a **Discloud Discord bot**:

- `TYPE=bot`
- `MAIN=bot.py`
- `DISCORD_BOT_TOKEN` must be set in the app's environment/secrets.
- The existing Discloud app name is retained so the deployment workflow can update that bot rather than create a website.

The GitHub Actions deployment workflow runs after the test suite succeeds and packages the Python bot, recipe data, and Discloud configuration.

## Local run

Install dependencies from `requirements.txt`, set `DISCORD_BOT_TOKEN`, then run:

```bash
python bot.py
```

## Scope

This project is now focused on the FiveM crafting directory. The former ALU code is retained in the Git history and repository during the migration, but the active bot entry point no longer loads the ALU dashboard or its MongoDB player-state features.

This is a FiveM roleplay game reference only, not real-world instructions.
