# FiveM Crafting Directory

A standalone, searchable reference for fictional crafting recipes used in FiveM roleplay servers.

## Current site

- `index.html` — responsive directory interface with table and recipe dropdowns, searchable recipe cards, and a recipe detail panel.
- `recipes.json` — crafting table and recipe data.
- `server.py` — optional lightweight Python static-file server (listens on `0.0.0.0:$PORT`, default `8080`).

## Included data

The first imported table is **Glovebox Table**, transcribed from the in-game screenshots supplied for this project. Each recipe shows its required items and quantities separately from reusable tools (tools are not consumed).

More crafting tables will be added from the existing screenshot workbook after their OCR text is checked against the original images. The earlier workbook contains uncertain OCR, so those entries are not silently published as verified recipes.

## Run locally

Python 3.10+:

```bash
python server.py
```

Then open `http://localhost:8080`.

You can also open `index.html` directly in a browser, provided `recipes.json` stays beside it.

## Deploying to Discloud

This is now a website, not a Discord bot. Discloud website hosting requires a `TYPE=site` configuration, a registered site ID/subdomain, port 8080 for dynamic servers, and (according to current Discloud documentation) a Platinum plan or higher. A static HTML site can use `MAIN=index.html`.

Before switching the existing Discloud app, confirm the registered Discloud site ID and hosting plan. The current `discloud.config` and automated deployment workflow are intentionally left unchanged for now so the existing live app is not accidentally overwritten or broken.

## Data quality

- **Screenshot transcribed:** readable entries captured from the supplied in-game screenshot.
- **Needs review:** OCR-derived entries must be checked against their original screenshots before publication.
- Server resources can change recipe names, quantities, and required tools. Treat this as a community reference and verify in-game.

This directory is for FiveM roleplay game data only; it does not describe real-world procedures.
