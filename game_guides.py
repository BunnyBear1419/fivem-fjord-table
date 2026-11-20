"""Safe, game-only location guide lookups for the Fjord Cartel bot.

This module stores navigation and roleplay reminders, not chemical recipes or
process parameters.
"""
import re


def get_game_guide(query: str):
    """Return the Meth System #1 navigation guide for natural-language questions."""
    normalized = re.sub(r"[^a-z0-9]+", " ", str(query or "").casefold()).strip()
    phrases = (
        "how to cook meth",
        "how do i cook meth",
        "meth system 1",
        "meth system one",
        "meth cooking",
        "meth cook guide",
        "meth guide",
    )
    if not any(phrase in normalized for phrase in phrases):
        return None

    return {
        "title": "Meth System #1 — In-Game Location Guide",
        "description": (
            "FiveM roleplay reference. Use the postal codes with your in-game map/GPS. "
            "NPC encounters may occur at some pickup locations, so stay alert."
        ),
        "fields": [
            ("1 · Cooking kit", "Postal **4013** — Meth Cook Kit pickup. Check the in-game map for the marked spot."),
            ("2 · Supply pickup", "Postal **3024** — supply pickup location. Check the in-game map for the marker."),
            ("3 · Additional pickup points", "Postals **2060**, **10065**, and **10066** — additional pickup locations."),
            ("4 · Hidden Shed", "Postal **3043** — Hidden Shed. If the shed does not appear, try the in-game F8/reload workaround you use on this server, then check the location again. Use the third-eye interaction to enter when available."),
            ("5 · Junkyard", "Postal **3048** — junkyard / vehicle interaction area."),
            ("6 · RVs and Campers", "Postal **4024** — RV/Camper area. The location tracker records RVs and Campers here."),
            ("In-game cooking interaction", "Once you reach the RV/Camper, use the server's in-game interaction prompts and crafting directory for the current minigame requirements. This bot guide is for navigation and does not provide chemical-processing steps or temperature settings."),
            ("Safety reminder", "Some pickup spots may have hostile NPCs. Watch your surroundings and follow the server's roleplay rules."),
        ],
        "footer": "FJORD CARTEL • FIVE M ROLEPLAY LOCATION REFERENCE",
    }
