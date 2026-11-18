"""Low-memory reporting, export, validation and comparison helpers for the crafting bot."""
import csv
import io
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from typing import Any

import discord



# --- Natural-language shop price calculator ---

SHOP_PRICE_CATALOG = [
    {"name": "Repair Kit", "shop": "PDM", "price": 2000, "aliases": ("repair kit", "repair kits")},
    {"name": "Contract", "shop": "PDM — Special Role Required", "price": 1000, "aliases": ("contract", "contracts")},
    {"name": "Phone", "shop": "Digital Den", "price": 500, "aliases": ("phone",)},
    {"name": "Radio", "shop": "Digital Den", "price": 500, "aliases": ("radio",)},
    {"name": "Laptop", "shop": "Digital Den", "price": 2000, "aliases": ("laptop",)},
    {"name": "Pistol Ammo", "shop": "Weapon & Ammo Store", "price": 10, "aliases": ("pistol ammo", "pistol bullets", "pistol bullet")},
    {"name": "Rifle Ammo (5.56)", "shop": "Weapon & Ammo Store", "price": 20, "aliases": ("rifle ammo 556", "rifle ammo 5.56", "rifle ammo (5.56)", "5.56 rifle ammo", "556 ammo", "5.56 ammo", "556 bullets", "5.56 bullets")},
    {"name": "SMG Ammo (.45 ACP)", "shop": "Weapon & Ammo Store", "price": 23, "aliases": ("45 ammo", ".45 ammo", "45 acp", ".45 acp", "45 acp ammo", "smg ammo", "smg bullets")},
    {"name": "Rifle Ammo (7.62)", "shop": "Weapon & Ammo Store", "price": 25, "aliases": ("rifle ammo 762", "rifle ammo 7.62", "rifle ammo (7.62)", "7.62 rifle ammo", "762 ammo", "7.62 ammo", "762 bullets", "7.62 bullets")},
    {"name": "Shotgun Ammo (12 Gauge)", "shop": "Weapon & Ammo Store", "price": 55, "aliases": ("shotgun ammo", "12 gauge ammo", "12 gauge shells", "shotgun shells")},
    {"name": "Black Pistol", "shop": "Weapon & Ammo Store", "price": 2000, "aliases": ("black pistol",)},
    {"name": "Pink Pistol", "shop": "Weapon & Ammo Store", "price": 4800, "aliases": ("pink pistol",)},
    {"name": "Snowball", "shop": "Weapon & Ammo Store", "price": 100, "aliases": ("snowball",)},
    {"name": "Bat", "shop": "Weapon & Ammo Store", "price": 250, "aliases": ("bat",)},
    {"name": "Knife", "shop": "Weapon & Ammo Store", "price": 250, "aliases": ("knife",)},
    {"name": "Distilled Water", "shop": "Chemical Supplier — Postal 10105", "price": 20, "aliases": ("distilled water",)},
    {"name": "Sodium Hydroxide (Lye)", "shop": "Chemical Supplier — Postal 10105", "price": 80, "aliases": ("sodium hydroxide", "sodium hydroxide lye", "lye")},
    {"name": "Citric Acid", "shop": "Chemical Supplier — Postal 10105", "price": 20, "aliases": ("citric acid",)},
    {"name": "Sulfuric Acid", "shop": "Chemical Supplier — Postal 10105", "price": 50, "aliases": ("sulfuric acid",)},
    {"name": "Slaked Lime", "shop": "Chemical Supplier — Postal 10105", "price": 15, "aliases": ("slaked lime",)},
    {"name": "Succinic Acid", "shop": "Chemical Supplier — Postal 10105", "price": 40, "aliases": ("succinic acid",)},
    {"name": "Acetone", "shop": "Chemical Supplier — Postal 10105", "price": 60, "aliases": ("acetone",)},
    {"name": "Isopropyl Alcohol", "shop": "Chemical Supplier — Postal 10105", "price": 50, "aliases": ("isopropyl alcohol", "isopropanol")},
    {"name": "Naphtha", "shop": "Chemical Supplier — Postal 10105", "price": 70, "aliases": ("naphtha",)},
    {"name": "Grain Alcohol", "shop": "Chemical Supplier — Postal 10105", "price": 45, "aliases": ("grain alcohol",)},
    {"name": "Butane Canister", "shop": "Chemical Supplier — Postal 10105", "price": 30, "aliases": ("butane canister", "butane")},
    {"name": "Sodium Benzoate", "shop": "Chemical Supplier — Postal 10105", "price": 150, "aliases": ("sodium benzoate",)},
    {"name": "Ammonia", "shop": "Chemical Supplier — Postal 10105", "price": 175, "aliases": ("ammonia",)},
    {"name": "Hydrogen Peroxide", "shop": "Chemical Supplier — Postal 10105", "price": 40, "aliases": ("hydrogen peroxide",)},
    {"name": "Urea", "shop": "Chemical Supplier — Postal 10105", "price": 25, "aliases": ("urea",)},
    {"name": "Formaldehyde", "shop": "Chemical Supplier — Postal 10105", "price": 60, "aliases": ("formaldehyde",)},
    {"name": "Potassium Permanganate", "shop": "Chemical Supplier — Postal 10105", "price": 60, "aliases": ("potassium permanganate",)},
    {"name": "Sodium Acetate", "shop": "Chemical Supplier — Postal 10105", "price": 40, "aliases": ("sodium acetate",)},
    {"name": "Filter Paper", "shop": "Chemical Supplier — Postal 10105", "price": 10, "aliases": ("filter paper", "filter papers")},
    {"name": "Weed seed", "shop": "Farm Supplier — Postals 2002–2003", "price": 60, "aliases": ("weed seed", "weed seeds",)},
    {"name": "Cocaine seed", "shop": "Farm Supplier — Postals 2002–2003", "price": 150, "aliases": ("cocaine seed", "cocaine seeds",)},
    {"name": "Poppy seeds", "shop": "Farm Supplier — Postals 2002–2003", "price": 120, "aliases": ("poppy seed", "poppy seeds",)},
    {"name": "Birch Sapling", "shop": "Farm Supplier — Postals 2002–2003", "price": 200, "aliases": ("birch sapling", "birch saplings",)},
    {"name": "San Pedro Cuttings", "shop": "Farm Supplier — Postals 2002–2003", "price": 90, "aliases": ("san pedro cutting", "san pedro cuttings",)},
    {"name": "Watering can", "shop": "Farm Supplier — Postals 2002–2003", "price": 15, "aliases": ("watering can", "watering cans",)},
    {"name": "Rainwater Jug", "shop": "Farm Supplier — Postals 2002–2003", "price": 20, "aliases": ("rainwater jug", "rainwater jugs",)},
    {"name": "Spring Water", "shop": "Farm Supplier — Postals 2002–2003", "price": 20, "aliases": ("spring water",)},
    {"name": "Pond Water", "shop": "Farm Supplier — Postals 2002–2003", "price": 15, "aliases": ("pond water",)},
    {"name": "Misting Bottle", "shop": "Farm Supplier — Postals 2002–2003", "price": 20, "aliases": ("misting bottle", "misting bottles",)},
    {"name": "Fertilizer", "shop": "Farm Supplier — Postals 2002–2003", "price": 40, "aliases": ("fertilizer",)},
    {"name": "Cactus Fertilizer", "shop": "Farm Supplier — Postals 2002–2003", "price": 50, "aliases": ("cactus fertilizer",)},
    {"name": "Tropical Fertilizer", "shop": "Farm Supplier — Postals 2002–2003", "price": 60, "aliases": ("tropical fertilizer",)},
    {"name": "Fish Emulsion", "shop": "Farm Supplier — Postals 2002–2003", "price": 50, "aliases": ("fish emulsion",)},
    {"name": "Bone Meal", "shop": "Farm Supplier — Postals 2002–2003", "price": 45, "aliases": ("bone meal",)},
    {"name": "Bloom Booster", "shop": "Farm Supplier — Postals 2002–2003", "price": 70, "aliases": ("bloom booster",)},
    {"name": "Organic Compost", "shop": "Farm Supplier — Postals 2002–2003", "price": 55, "aliases": ("organic compost",)},
    {"name": "Birch Leaf Mulch", "shop": "Farm Supplier — Postals 2002–2003", "price": 45, "aliases": ("birch leaf mulch",)},
    {"name": "Aquatic Fertilizer Tabs", "shop": "Farm Supplier — Postals 2002–2003", "price": 50, "aliases": ("aquatic fertilizer tabs", "aquatic fertilizer tab",)},
    {"name": "Cactus Soil Mix", "shop": "Farm Supplier — Postals 2002–2003", "price": 40, "aliases": ("cactus soil mix",)},
    {"name": "Peat Moss", "shop": "Farm Supplier — Postals 2002–2003", "price": 40, "aliases": ("peat moss",)},
    {"name": "Trowel", "shop": "Farm Supplier — Postals 2002–2003", "price": 100, "aliases": ("trowel",)},
    {"name": "Flower Pot", "shop": "Farm Supplier — Postals 2002–2003", "price": 250, "aliases": ("flower pot", "flower pots",)},
    {"name": "Portable Lamp (Standard)", "shop": "Farm Supplier — Postals 2002–2003", "price": 750, "aliases": ("portable lamp standard", "standard portable lamp",)},
    {"name": "Portable Lamp (Large)", "shop": "Farm Supplier — Postals 2002–2003", "price": 1250, "aliases": ("portable lamp large", "large portable lamp",)},
    {"name": "Garden Trellis", "shop": "Farm Supplier — Postals 2002–2003", "price": 150, "aliases": ("garden trellis", "trellis",)},
    {"name": "Shade Cloth", "shop": "Farm Supplier — Postals 2002–2003", "price": 120, "aliases": ("shade cloth",)},
    {"name": "Pond Tub", "shop": "Farm Supplier — Postals 2002–2003", "price": 250, "aliases": ("pond tub", "pond tubs",)},
    {"name": "Piperazine", "shop": "Farm Supplier — Postals 2002–2003", "price": 80, "aliases": ("piperazine",)},
    {"name": "Whole Nutmeg", "shop": "Farm Supplier — Postals 2002–2003", "price": 10, "aliases": ("whole nutmeg", "nutmeg",)},
    {"name": "Mortar and Pestle", "shop": "Farm Supplier — Postals 2002–2003", "price": 60, "aliases": ("mortar and pestle", "mortar pestle",)},
    {"name": "Bag of Corn", "shop": "Farmers Market", "price": 10, "aliases": ("bag of corn", "corn")},
    {"name": "Bag of Sugar", "shop": "Farmers Market", "price": 10, "aliases": ("bag of sugar", "sugar")},
    {"name": "Bag of Yeast", "shop": "Farmers Market", "price": 10, "aliases": ("bag of yeast", "yeast")},
    {"name": "Gallon of Water", "shop": "Farmers Market", "price": 5, "aliases": ("gallon of water",)},
    {"name": "Empty Barrel", "shop": "Farmers Market", "price": 100, "aliases": ("empty barrel", "barrel")},
    {"name": "Empty Jug", "shop": "Farmers Market", "price": 50, "aliases": ("empty jug", "jug")},
    {"name": "Propane", "shop": "Hidden Locations — Postals 1012 & 2006", "price": 1000, "aliases": ("propane", "propane tank", "filled propane container")},
    {"name": "Meth Cooking Station", "shop": "Hidden Location — Postal 2006", "price": 15000, "aliases": ("meth cooking station", "meth station")},
    {"name": "RV Meth Cooking Kit", "shop": "Hidden Location — Postal 2006", "price": 10000, "aliases": ("rv meth cooking kit", "meth rv cooking kit", "rv cooking kit")},
    {"name": "Ethanol Distiller", "shop": "Hidden Location — Postal 2006", "price": 25000, "aliases": ("ethanol distiller", "etanol distiller")},
    {"name": "Meth Table", "shop": "Equipment Dealer — Postals 9275–9277", "price": 5000, "aliases": ("meth table",)},
    {"name": "Weed Table", "shop": "Equipment Dealer — Postals 9275–9277", "price": 4000, "aliases": ("weed table",)},
    {"name": "Coke Table", "shop": "Equipment Dealer — Postals 9275–9277", "price": 5000, "aliases": ("coke table", "cocaine table")},
    {"name": "Chemistry Table", "shop": "Equipment Dealer — Postals 9275–9277", "price": 6500, "aliases": ("chemistry table",)},
    {"name": "Pill Press", "shop": "Equipment Dealer — Postals 9275–9277", "price": 7500, "aliases": ("pill press",)},
    {"name": "Reflux Rig", "shop": "Equipment Dealer — Postals 9275–9277", "price": 9000, "aliases": ("reflux rig",)},
    {"name": "Extraction Bench", "shop": "Equipment Dealer — Postals 9275–9277", "price": 8000, "aliases": ("extraction bench",)},
    {"name": "Glovebox", "shop": "Equipment Dealer — Postals 9275–9277", "price": 15000, "aliases": ("glovebox", "glove box")},
    {"name": "Brewing Kettle", "shop": "Equipment Dealer — Postals 9275–9277", "price": 2500, "aliases": ("brewing kettle",)},
    {"name": "Lab Freezer", "shop": "Equipment Dealer — Postals 9275–9277", "price": 4000, "aliases": ("lab freezer",)},
    {"name": "Herb Drying Rack", "shop": "Equipment Dealer — Postals 9275–9277", "price": 2000, "aliases": ("herb drying rack",)},
    {"name": "Grinding Station", "shop": "Equipment Dealer — Postals 9275–9277", "price": 3000, "aliases": ("grinding station",)},
    {"name": "Capsule Filler", "shop": "Equipment Dealer — Postals 9275–9277", "price": 3500, "aliases": ("capsule filler",)},
    {"name": "Burner Phone", "shop": "Equipment Dealer — Postals 9275–9277", "price": 500, "aliases": ("burner phone", "burner phones")},
    {"name": "Tablet Die Set", "shop": "Equipment Dealer — Postals 9275–9277", "price": 1200, "aliases": ("tablet die set", "tablet die")},
    {"name": "Hand Tablet Press", "shop": "Equipment Dealer — Postals 9275–9277", "price": 900, "aliases": ("hand tablet press", "tablet press")},
    {"name": "Cookie dough", "shop": "Head Shop — Postal 3057", "price": 75, "aliases": ("cookie dough", "cookie doughs")},
    {"name": "Chocolate chips", "shop": "Head Shop — Postal 3057", "price": 50, "aliases": ("chocolate chips", "chocolate chip")},
    {"name": "Baking soda", "shop": "Head Shop — Postal 3057", "price": 10, "aliases": ("baking soda",)},
    {"name": "Grapeseed Oil", "shop": "Head Shop — Postal 3057", "price": 25, "aliases": ("grapeseed oil", "grape seed oil")},
    {"name": "Plastic bag", "shop": "Head Shop — Postal 3057", "price": 5, "aliases": ("plastic bag", "plastic bags")},
    {"name": "Styrofoam Cup", "shop": "Head Shop — Postal 3057", "price": 15, "aliases": ("styrofoam cup", "styrofoam cups")},
    {"name": "2L Plastic Bottle", "shop": "Head Shop — Postal 3057", "price": 5, "aliases": ("2l plastic bottle", "2 liter plastic bottle", "2 litre plastic bottle")},
    {"name": "Aluminum Foil", "shop": "Head Shop — Postal 3057", "price": 10, "aliases": ("aluminum foil", "aluminium foil")},
    {"name": "Art papers", "shop": "Head Shop — Postal 3057", "price": 150, "aliases": ("art papers", "art paper")},
    {"name": "Nitrous Oxide Charger", "shop": "Head Shop — Postal 3057", "price": 15, "aliases": ("nitrous oxide charger", "nitrous charger")},
    {"name": "Balloon", "shop": "Head Shop — Postal 3057", "price": 5, "aliases": ("balloon", "balloons")},
    {"name": "Cigarette", "shop": "Head Shop — Postal 3057", "price": 5, "aliases": ("cigarette",)},
    {"name": "Weed papers", "shop": "Head Shop — Postal 3057", "price": 30, "aliases": ("weed papers", "weed paper")},
    {"name": "Pipe", "shop": "Head Shop — Postal 3057", "price": 10, "aliases": ("pipe", "smoking pipe")},
    {"name": "Cheesecloth", "shop": "Head Shop — Postal 3057", "price": 5, "aliases": ("cheesecloth", "cheese cloth")},
    {"name": "Firewood", "shop": "Log Market — Postal 1082", "price": 10, "aliases": ("firewood", "fire wood",)},
    {"name": "Lockpick", "shop": "Convenience Store", "price": 20, "aliases": ("lockpick", "lock picks")},
    {"name": "Jerry Can", "shop": "Convenience Store", "price": 200, "aliases": ("jerry can", "gas can")},
    {"name": "Outfit Bag", "shop": "Convenience Store", "price": 5000, "aliases": ("outfit bag",)},
    {"name": "Classic Chips", "shop": "Convenience Store", "price": 3, "aliases": ("classic chips",)},
    {"name": "Cheese Chips", "shop": "Convenience Store", "price": 3, "aliases": ("cheese chips",)},
    {"name": "Salted Chips", "shop": "Convenience Store", "price": 3, "aliases": ("salted chips",)},
    {"name": "Ribs Chips", "shop": "Convenience Store", "price": 4, "aliases": ("ribs chips",)},
    {"name": "Habanero Chips", "shop": "Convenience Store", "price": 5, "aliases": ("habanero chips",)},
    {"name": "Redwood Cigarettes", "shop": "Convenience Store", "price": 5, "aliases": ("redwood cigarettes", "cigarettes", "cigs")},
    {"name": "Vape", "shop": "Convenience Store", "price": 1000, "aliases": ("vape",)},
    {"name": "Hot Dog", "shop": "Convenience Store", "price": 2, "aliases": ("hot dog", "hot dogs", "hotdog", "hotdogs")},
    {"name": "Homemade Sandwich", "shop": "Convenience Store", "price": 3, "aliases": ("homemade sandwich", "sandwich")},
    {"name": "Chicken Noodles", "shop": "Convenience Store", "price": 3, "aliases": ("chicken noodles",)},
    {"name": "Seafood Noodles", "shop": "Convenience Store", "price": 3, "aliases": ("seafood noodles",)},
    {"name": "E-Cola", "shop": "Convenience Store", "price": 3, "aliases": ("e cola", "e-cola")},
    {"name": "E-Cola Light", "shop": "Convenience Store", "price": 3, "aliases": ("e cola light", "e-cola light")},
    {"name": "Orang-O-Tang", "shop": "Convenience Store", "price": 3, "aliases": ("orang o tang", "orang-o-tang")},
    {"name": "Sprunk", "shop": "Convenience Store", "price": 3, "aliases": ("sprunk",)},
    {"name": "Sprunk Bottle", "shop": "Convenience Store", "price": 3, "aliases": ("sprunk bottle",)},
    {"name": "Sprunk Light", "shop": "Convenience Store", "price": 4, "aliases": ("sprunk light",)},
    {"name": "E-Cola Bottle", "shop": "Convenience Store", "price": 4, "aliases": ("e cola bottle", "e-cola bottle")},
    {"name": "Orang-O-Tang Bottle", "shop": "Convenience Store", "price": 4, "aliases": ("orang o tang bottle", "orang-o-tang bottle")},
    {"name": "E-Cola Light Bottle", "shop": "Convenience Store", "price": 5, "aliases": ("e cola light bottle", "e-cola light bottle")},
    {"name": "Sprunk Light Bottle", "shop": "Convenience Store", "price": 5, "aliases": ("sprunk light bottle",)},
    {"name": "Safrole oil", "shop": "Blackmarket Doctor — Postal 3009", "price": 200, "aliases": ("safrole oil", "safrole")},
    {"name": "NPP chemical", "shop": "Blackmarket Doctor — Postal 3009", "price": 300, "aliases": ("npp chemical", "npp")},
    {"name": "Aniline solution", "shop": "Blackmarket Doctor — Postal 3009", "price": 250, "aliases": ("aniline solution", "aniline")},
    {"name": "Anesthetic", "shop": "Blackmarket Doctor — Postal 3009", "price": 250, "aliases": ("anesthetic", "anaesthetic")},
    {"name": "Dextromethorphan Cough Syrup", "shop": "Blackmarket Doctor — Postal 3009", "price": 60, "aliases": ("dextromethorphan cough syrup", "dextromethorphan")},
    {"name": "Syringe", "shop": "Blackmarket Doctor — Postal 3009", "price": 15, "aliases": ("syringe", "syringes")},
    {"name": "Bandage", "shop": "Pharmacy — Postal 9072", "price": 150, "aliases": ("bandage", "bandages",)},
    {"name": "Feminine Pad", "shop": "Pharmacy — Postal 9072", "price": 10, "aliases": ("feminine pad", "feminine pads",)},
    {"name": "Chill Pills", "shop": "Pharmacy — Postal 9072", "price": 100, "aliases": ("chill pills", "chill pill",)},
    {"name": "Electrolyte Drink", "shop": "Pharmacy — Postal 9072", "price": 20, "aliases": ("electrolyte drink", "electrolyte drinks",)},
    {"name": "Cough Syrup", "shop": "Pharmacy — Postal 9072", "price": 50, "aliases": ("cough syrup",)},
    {"name": "Condoms", "shop": "Pharmacy — Postal 9072", "price": 10, "aliases": ("condom", "condoms",)},
    {"name": "Pregnancy Test Box", "shop": "Pharmacy — Postal 9072", "price": 200, "aliases": ("pregnancy test box", "pregnancy test", "pregnancy tests",)},
    {"name": "Prenatal Vitamins", "shop": "Pharmacy — Postal 9072", "price": 100, "aliases": ("prenatal vitamins", "prenatal vitamin",)},
    {"name": "Baby Oil", "shop": "Pharmacy — Postal 9072", "price": 50, "aliases": ("baby oil",)},
    {"name": "Confetti Cannon", "shop": "Pharmacy — Postal 9072", "price": 50, "aliases": ("confetti cannon", "confetti cannons",)},
    {"name": "Confetti Popper", "shop": "Pharmacy — Postal 9072", "price": 50, "aliases": ("confetti popper", "confetti poppers",)},
    {"name": "Gender Reveal Balloon", "shop": "Pharmacy — Postal 9072", "price": 50, "aliases": ("gender reveal balloon", "gender reveal balloons",)},
    {"name": "Gender Reveal Gift Box", "shop": "Pharmacy — Postal 9072", "price": 50, "aliases": ("gender reveal gift box", "gender reveal gift boxes",)},
    {"name": "Gender Reveal Smoke", "shop": "Pharmacy — Postal 9072", "price": 50, "aliases": ("gender reveal smoke",)},

    {"name": "Old Boot", "shop": "Scuba Diving Shop", "price": 15, "aliases": ("old boot",)},
    {"name": "Wood Plank", "shop": "Scuba Diving Shop", "price": 15, "aliases": ("wood plank", "wood planks",)},
    {"name": "Rusted Padlock", "shop": "Scuba Diving Shop", "price": 15, "aliases": ("rusted padlock", "rusted padlocks",)},
    {"name": "Rusted Key", "shop": "Scuba Diving Shop", "price": 15, "aliases": ("rusted key", "rusted keys",)},
    {"name": "Rusted Gear", "shop": "Scuba Diving Shop", "price": 15, "aliases": ("rusted gear",)},
    {"name": "Seashell", "shop": "Scuba Diving Shop", "price": 43, "aliases": ("seashell", "sea shell", "seashells",)},
    {"name": "Seaweed", "shop": "Scuba Diving Shop", "price": 43, "aliases": ("seaweed",)},
    {"name": "Rusted Muffler", "shop": "Scuba Diving Shop", "price": 43, "aliases": ("rusted muffler", "rusted mufflers",)},
    {"name": "Broken CD", "shop": "Scuba Diving Shop", "price": 43, "aliases": ("broken cd", "broken cds",)},
    {"name": "Diving Goggles", "shop": "Scuba Diving Shop", "price": 43, "aliases": ("diving goggles", "goggles",)},
    {"name": "Fishing Net", "shop": "Scuba Diving Shop", "price": 70, "aliases": ("fishing net", "fishing nets",)},
    {"name": "Old Camera", "shop": "Scuba Diving Shop", "price": 70, "aliases": ("old camera", "old cameras",)},
    {"name": "Military Helmet", "shop": "Scuba Diving Shop", "price": 70, "aliases": ("military helmet", "military helmets",)},
    {"name": "Old Compass", "shop": "Scuba Diving Shop", "price": 93, "aliases": ("old compass", "old compasses",)},
    {"name": "Old Watch", "shop": "Scuba Diving Shop", "price": 93, "aliases": ("old watch", "old watches",)},
    {"name": "Conch Shell", "shop": "Scuba Diving Shop", "price": 93, "aliases": ("conch shell", "conch shells",)},
    {"name": "Treasure Map", "shop": "Scuba Diving Shop", "price": 40, "aliases": ("treasure map", "treasure maps",)},
    {"name": "Silver Bracelet", "shop": "Scuba Diving Shop", "price": 55, "aliases": ("silver bracelet", "silver bracelets",)},
    {"name": "Ancient Artifact", "shop": "Scuba Diving Shop", "price": 78, "aliases": ("ancient artifact", "ancient artifacts",)},
    {"name": "Oxygen Tank", "shop": "The Gear Shop", "price": 100, "aliases": ("oxygen tank", "oxygen tanks",)},
    {"name": "Scuba Gear Level 1", "shop": "The Gear Shop", "price": 250, "aliases": ("scuba gear level 1", "scuba gear 1", "level 1 scuba gear",)},
    {"name": "Scuba Gear Level 2", "shop": "The Gear Shop", "price": 500, "aliases": ("scuba gear level 2", "scuba gear 2", "level 2 scuba gear",)},
    {"name": "Scuba Gear Level 3", "shop": "The Gear Shop", "price": 1000, "aliases": ("scuba gear level 3", "scuba gear 3", "level 3 scuba gear",)},
    {"name": "Scuba Gear Level 4", "shop": "The Gear Shop", "price": 2000, "aliases": ("scuba gear level 4", "scuba gear 4", "level 4 scuba gear",)},
    {"name": "Scuba Gear Level 5", "shop": "The Gear Shop", "price": 5000, "aliases": ("scuba gear level 5", "scuba gear 5", "level 5 scuba gear",)},
    {"name": "Burger", "shop": "The Gear Shop", "price": 5, "aliases": ("burger",)},
    {"name": "Water", "shop": "The Gear Shop", "price": 5, "aliases": ("water",)},
    {"name": "24-hour Boat Rental Deposit", "shop": "The Gear Shop — refundable when returned", "price": 500, "aliases": ("24 hour boat rental", "24-hour boat rental", "boat rental", "boat rental deposit",)},
]




def calculate_raw_cocaine_requirements(query: str):
    """Estimate pickup materials for a requested Raw Cocaine target."""
    raw = str(query or "").strip()
    if not re.search(r"\braw\s+cocaine\b", raw, re.IGNORECASE):
        return None
    match = re.search(r"([0-9][0-9,]*)\s*(?:x\s*)?(?:raw\s+)?cocaine\b", raw, re.IGNORECASE)
    if not match:
        return None
    target = int(match.group(1).replace(",", ""))
    if target < 1 or target > 1_000_000_000:
        return {"error": "Please enter a Raw Cocaine target between 1 and 1,000,000,000."}
    picks = (target + 799) // 800
    return {
        "target": target,
        "picks": picks,
        "estimated_output": picks * 800,
        "materials": {"Cement": picks * 6, "Hydrochloric Acid": picks * 4, "Gasoline": picks * 8},
        "total_cost": 0,
    }


def calculate_poppy_growing_requirements(query: str):
    """Calculate the supplied in-game Poppy Plant shopping list."""
    raw = str(query or "").strip()
    if not re.search(r"\bpopp(?:y|ies|ly)\b", raw, re.IGNORECASE) or not re.search(r"\b(?:plant|plants|grow|growing)\b", raw, re.IGNORECASE):
        return None
    match = re.search(r"([0-9][0-9,]*)\s*(?:x\s*)?(?:poppy\s+)?plants?\b", raw, re.IGNORECASE)
    if not match:
        match = re.search(r"\b(?:grow|growing)\s+([0-9][0-9,]*)\b", raw, re.IGNORECASE)
    plants = int(match.group(1).replace(",", "")) if match else 1
    if plants < 1 or plants > 100000:
        return {"error": "Please enter a plant amount between 1 and 100,000."}
    prices = {"Poppy Seed": 120, "Rainwater Jug": 20, "Bone Meal": 45, "Trowel": 100}
    items = {"Poppy Seed": plants, "Rainwater Jug": plants, "Bone Meal": plants, "Trowel": 1}
    costs = {name: prices[name] * quantity for name, quantity in items.items()}
    return {
        "plants": plants,
        "items": items,
        "costs": costs,
        "total": sum(costs.values()),
        "note": "Each Poppy Plant needs 1 Poppy Seed, 1 Rainwater Jug, and 1 Bone Meal. The Trowel is reusable, so only 1 is needed for the whole planting session.",
    }


def calculate_weed_growing_requirements(query: str):
    """Calculate shopping requirements for either of the two in-city weed systems."""
    raw = str(query or "").strip()
    if not re.search(r"\bweed\b", raw, re.IGNORECASE) or not re.search(r"\b(?:plant|plants|grow|growing)\b", raw, re.IGNORECASE):
        return None
    match = re.search(r"([0-9][0-9,]*)\s*(?:x\s*)?(?:weed\s+)?plants?\b", raw, re.IGNORECASE)
    if not match:
        match = re.search(r"\b(?:grow|growing)\s+([0-9][0-9,]*)\b", raw, re.IGNORECASE)
    plants = int(match.group(1).replace(",", "")) if match else 1
    if plants < 1 or plants > 100000:
        return {"error": "Please enter a plant amount between 1 and 100,000."}
    grass = bool(re.search(r"\b(?:grass|in\s+the\s+grass)\b", raw, re.IGNORECASE))
    prices = {
        "Female/Male Seed (choose one)": 60, "Weed Seed": 60,
        "Fertilizer": 40, "Spring Water": 20, "Rainwater Jug": 20,
        "Flower Pot": 250, "Trowel": 100, "Bloom Booster": 70, "Watering Can": 15,
    }
    systems = {
        "smoke": {
            "name": "System 1 — Smoke On The Water + Grapeseed",
            "items": {
                "Female/Male Seed (choose one)": plants, "Fertilizer": plants,
                "Spring Water": plants, "Watering Can": plants, "Trowel": 1, "Flower Pot": plants,
            },
            "locations": {
                "Smoke On The Water": ["Female/Male Seed (choose one)", "Spring Water"],
                "Grapeseed": ["Fertilizer", "Watering Can", "Trowel", "Flower Pot"],
            },
            "note": "Choose either Female Seed or Male Seed from Smoke On The Water (one seed per plant). Buy Fertilizer, one Watering Can per plant, the reusable Trowel, and Flower Pots at Grapeseed, plus Spring Water at Smoke On The Water. One Flower Pot and one Watering Can are required for every plant, including plants placed on grass.",
        },
        "grape": {
            "name": "System 2 — Grapeseed",
            "items": {
                "Weed Seed": plants, "Rainwater Jug": plants,
                "Bloom Booster": plants, "Trowel": 1,
                **({} if grass else {"Flower Pot": plants}),
            },
            "locations": {
                "Grapeseed": ["Weed Seed", "Rainwater Jug", "Bloom Booster", "Trowel"] + ([] if grass else ["Flower Pot"]),
            },
            "note": "System 2 uses one Weed Seed, one Rainwater Jug, and one Bloom Booster per plant. No Spring Water or Watering Can is required. The Trowel is reusable; a Flower Pot is only needed when planting off grass.",
        },
    }
    total_cost = lambda items: sum(prices[item] * quantity for item, quantity in items.items())
    return {
        "plants": plants,
        "grass": grass,
        "systems": {
            key: {
                **value,
                "costs": {item: prices[item] * quantity for item, quantity in value["items"].items()},
                "total": total_cost(value["items"]),
            }
            for key, value in systems.items()
        },
    }


def calculate_shop_price_query(query: str):
    """Resolve shop/location price questions, with optional bulk quantity."""
    raw = str(query or "").strip()
    normalized = _normalize_chat_search(raw)
    price_intent = any(word in normalized for word in ("how much", "cost", "spend", "price", "total"))
    location_intent = "where" in normalized and any(word in normalized for word in ("buy", "get", "purchase", "find"))
    if not (price_intent or location_intent):
        return None

    quantity_match = re.search(r"(?<![a-z])([0-9][0-9,]*)\b", raw, re.IGNORECASE)
    quantity = int(quantity_match.group(1).replace(",", "")) if quantity_match else None
    if quantity is not None and (quantity < 1 or quantity > 1_000_000_000):
        return {"error": "Please enter a quantity between 1 and 1,000,000,000."}

    matches = []
    for item in SHOP_PRICE_CATALOG:
        for alias in item["aliases"]:
            alias_normalized = _normalize_chat_search(alias)
            if alias_normalized and re.search(r"(?<![a-z0-9])" + re.escape(alias_normalized) + r"(?![a-z0-9])", normalized):
                matches.append((len(alias_normalized), item))
    if not matches:
        return {"error": "I couldn't match that item to a priced shop or location listing. Try the item name from /dashboard."}

    matches.sort(key=lambda row: row[0], reverse=True)
    best_length = matches[0][0]
    best_items = {row[1]["name"]: row[1] for row in matches if row[0] == best_length}
    if len(best_items) != 1:
        names = ", ".join(sorted(best_items))
        return {"error": f"I found more than one possible item ({names}). Please use the full item name."}

    item = next(iter(best_items.values()))
    return {
        "quantity": quantity,
        "item": item["name"],
        "shop": item["shop"],
        "unit_price": item["price"],
        "total": quantity * item["price"] if quantity is not None else None,
    }


def calculate_shop_basket(items_text: str):
    """Estimate a shopping basket using exact known catalogue names and aliases."""
    quantities = parse_inventory(items_text)
    results, unknown = [], []
    for requested_name, quantity in quantities.items():
        needle = re.sub(r"[^a-z0-9]+", " ", requested_name.casefold()).strip()
        candidates = []
        for item in SHOP_PRICE_CATALOG:
            aliases = (item["name"], *item.get("aliases", ()))
            if any(needle == re.sub(r"[^a-z0-9]+", " ", str(alias).casefold()).strip() for alias in aliases):
                candidates.append(item)
        unique = {item["name"]: item for item in candidates}
        if len(unique) != 1:
            unknown.append(requested_name)
            continue
        item = next(iter(unique.values()))
        results.append({
            "requested": requested_name, "name": item["name"], "shop": item["shop"],
            "quantity": quantity, "unit_price": int(item["price"]),
            "total": int(item["price"]) * quantity,
        })
    shops = list(dict.fromkeys(item["shop"] for item in results))
    return {
        "items": results, "unknown": unknown,
        "total": sum(item["total"] for item in results),
        "by_shop": {shop: sum(item["total"] for item in results if item["shop"] == shop) for shop in shops},
    }


def _normalize_chat_search(value: str) -> str:
    """Normalize user input for matching without modifying saved recipe names."""
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _fuzzy_name_score(query: str, candidate: str) -> float:
    """Score exact, partial and misspelled names conservatively."""
    query_norm = _normalize_chat_search(query)
    candidate_norm = _normalize_chat_search(candidate)
    if not query_norm or not candidate_norm:
        return 0.0
    if query_norm == candidate_norm:
        return 1.0
    full_score = SequenceMatcher(None, query_norm, candidate_norm).ratio()
    if query_norm in candidate_norm or candidate_norm in query_norm:
        full_score = max(full_score, 0.94)

    query_words = query_norm.split()
    candidate_words = candidate_norm.split()
    if query_words and candidate_words:
        word_scores = []
        for word in query_words:
            best = max(SequenceMatcher(None, word, other).ratio() for other in candidate_words)
            word_scores.append(best)
        token_score = sum(word_scores) / len(word_scores)
        full_score = max(full_score, (full_score * 0.55) + (token_score * 0.45))
    return full_score


def chat_recipe_search(data: dict[str, Any], query: str, limit: int = 3):
    """Find close recipe or ingredient matches, including common spelling mistakes."""
    cleaned = _normalize_chat_search(query)
    prefixes = (
        "how do i make ", "how do you make ", "how to make ", "how can i make ",
        "how much ", "how many batches of ", "how many ", "make ", "recipe for ", "how do i craft ", "how to craft ",
        "where do i find ", "where do i get ", "where can i find ", "where can i get ",
        "where is ", "find ", "what is the recipe for ",
    )
    for prefix in prefixes:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            break
    for suffix in (" can i make", " can i craft", " can i produce", " can i get", " please", " pls", " for me"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[:-len(suffix)].strip()
    if not cleaned or not isinstance(limit, int) or limit < 1:
        return []

    recipe_matches = []
    for table in data.get("tables", []):
        for recipe in table.get("recipes", []):
            name = str(recipe.get("name", "")).strip()
            if not name:
                continue
            score = _fuzzy_name_score(cleaned, name)
            threshold = 0.68 if len(cleaned.replace(" ", "")) <= 5 else 0.58
            if score >= threshold:
                recipe_matches.append({
                    "table": table.get("name", "Unknown table"),
                    "recipe": name,
                    "ingredients": list(recipe.get("ingredients") or []),
                    "tools": list(recipe.get("tools") or []),
                    "notes": list(recipe.get("notes") or []),
                    "score": score,
                    "match_label": "Recipe match" if score >= 0.94 else "Closest spelling match",
                })
    if recipe_matches:
        recipe_matches.sort(key=lambda item: (-item["score"], item["recipe"].casefold(), item["table"].casefold()))
        return recipe_matches[:limit]

    ingredient_matches = []
    for table in data.get("tables", []):
        for recipe in table.get("recipes", []):
            for ingredient, quantity in recipe.get("ingredients") or []:
                ingredient_name = str(ingredient).strip()
                score = _fuzzy_name_score(cleaned, ingredient_name)
                threshold = 0.72 if len(cleaned.replace(" ", "")) <= 5 else 0.62
                if score >= threshold:
                    ingredient_matches.append({
                        "table": table.get("name", "Unknown table"),
                        "recipe": recipe.get("name", "Unknown recipe"),
                        "ingredients": [[ingredient_name, quantity]],
                        "tools": [],
                        "notes": list(recipe.get("notes") or []),
                        "score": score,
                        "match_label": f"Closest ingredient spelling: {ingredient_name}",
                    })
    ingredient_matches.sort(key=lambda item: (-item["score"], item["recipe"].casefold(), item["table"].casefold()))
    return ingredient_matches[:limit]



def parse_usable_item_sections(sections: list[tuple[str, str]]):
    """Convert the saved Usable Items display sections into searchable recipe tables."""
    grouped = {}
    for raw_title, raw_value in sections:
        section = re.sub(r"^[^A-Za-z0-9]+", "", str(raw_title or "")).strip()
        section = re.sub(r"\s+—\s+Pill Recipes \(\d+/\d+\)$", "", section).strip()
        if not section:
            continue
        table_name = f"Usable Item — {section}"
        recipes = grouped.setdefault(table_name, [])
        current_recipe = None
        for raw_line in str(raw_value or "").splitlines():
            line = raw_line.strip()
            recipe_match = re.match(r"• \*\*(.+?)\*\* — (.+)$", line)
            if recipe_match:
                recipe_name, ingredient_text = recipe_match.groups()
                ingredients = []
                for part in re.split(r"\s+\+\s+", ingredient_text):
                    ingredient_match = re.fullmatch(r"\s*(\d+)\s*x\s*(.+?)\s*", part)
                    if ingredient_match:
                        ingredients.append([ingredient_match.group(2).strip(), int(ingredient_match.group(1))])
                if ingredients:
                    current_recipe = {"name": recipe_name.strip(), "ingredients": ingredients, "tools": []}
                    recipes.append(current_recipe)
                else:
                    current_recipe = None
            elif current_recipe and "Tool (not consumed)" in line:
                for quantity, tool_name in re.findall(r"(\d+)\s*x\s*([^,+]+)", line):
                    current_recipe["tools"].append(tool_name.strip())
    return [
        {"name": table_name, "recipes": recipes}
        for table_name, recipes in grouped.items()
        if recipes
    ]



def attach_location_recipe_warnings(data: dict[str, Any], location_sections: list[tuple[str, str]]):
    """Copy recipe data and attach explicit caveats found in saved location notes."""
    combined = dict(data)
    tables = []
    for source_table in data.get("tables", []):
        table = dict(source_table)
        table["recipes"] = []
        for source_recipe in source_table.get("recipes", []):
            recipe = dict(source_recipe)
            recipe["notes"] = list(source_recipe.get("notes") or [])
            table["recipes"].append(recipe)
        tables.append(table)

    for _title, value in location_sections:
        for raw_line in str(value or "").splitlines():
            line = raw_line.strip()
            match = re.match(r"• \*\*(.+?):\*\*\s*(.+)$", line)
            if not match:
                continue
            label, details = match.groups()
            recipe_name = re.sub(r"\s*\(\+\d+ XP\)$", "", label).strip()
            if "hidden material" not in details.casefold():
                continue
            note = (
                "Postal 10060 location notes list 1 additional hidden material, "
                "but its exact item name is not recorded in the saved recipe table."
            )
            if recipe_name.casefold() == "heist drill":
                note += (
                    " The saved ingredient name 'drill_bit' also does not exactly match "
                    "the output name 'Tungsten Drill Bit'; confirm whether they are the same item."
                )
            for table in tables:
                for recipe in table.get("recipes", []):
                    if recipe.get("name", "").casefold().strip() == recipe_name.casefold():
                        if note not in recipe["notes"]:
                            recipe["notes"].append(note)
    combined["tables"] = tables
    return combined


def related_table_search(data: dict[str, Any], query: str, limit: int = 8):
    """Find tables related to broad topics, listing only saved recipes and ingredients."""
    cleaned = _normalize_chat_search(query)
    stop_words = {"what", "tables", "table", "have", "has", "anything", "to", "do", "with", "about", "related", "show", "me", "find", "which", "are", "the", "for", "and", "or", "any"}
    terms = {word for word in cleaned.split() if word not in stop_words and len(word) > 1}
    if not terms or not isinstance(limit, int) or limit < 1:
        return []
    synonym_groups = (
        {"weed", "marijuana", "cannabis", "bud", "buds", "ganja", "pot"},
        {"coke", "cocaine"},
    )
    expanded = set(terms)
    for group in synonym_groups:
        if terms & group:
            expanded.update(group)
    results = []
    for table in data.get("tables", []):
        matched_recipes, matched_terms = [], set()
        for recipe in table.get("recipes", []):
            recipe_name = str(recipe.get("name", "")).strip()
            ingredients = [str(row[0]).strip() for row in recipe.get("ingredients") or [] if isinstance(row, (list, tuple)) and row]
            normalized = _normalize_chat_search(" ".join([str(table.get("name", "")), recipe_name, *ingredients]))
            hits = {term for term in expanded if term in normalized.split()}
            if hits:
                matched_terms.update(hits)
                matched_recipes.append({"recipe": recipe_name, "ingredients": ingredients, "matched_terms": sorted(hits), "notes": list(recipe.get("notes") or [])})
        if matched_recipes:
            results.append({"table": str(table.get("name", "Unknown table")), "recipes": matched_recipes,
                            "matched_terms": sorted(matched_terms), "score": len(matched_terms) * 2 + len(matched_recipes)})
    results.sort(key=lambda item: (-item["score"], item["table"].casefold()))
    return results[:limit]


def calculate_recipe_ingredients(data: dict[str, Any], table_name: str, recipe_name: str, batches: int = 1):
    """Calculate a shopping list, summing repeated ingredient rows without altering source data."""
    if not isinstance(batches, int) or batches < 1 or batches > 999:
        raise ValueError("Batch count must be between 1 and 999.")
    table = next((t for t in data.get("tables", []) if t.get("name", "").casefold().strip() == table_name.casefold().strip()), None)
    if table is None:
        raise ValueError(f"Crafting table not found: {table_name}")
    recipe = next((r for r in table.get("recipes", []) if r.get("name", "").casefold().strip() == recipe_name.casefold().strip()), None)
    if recipe is None:
        raise ValueError(f"Recipe not found in {table_name}: {recipe_name}")
    totals = {}
    for name, quantity in recipe.get("ingredients") or []:
        totals[name] = totals.get(name, 0) + int(quantity) * batches
    return {"table": table["name"], "recipe": recipe["name"], "batches": batches, "ingredients": totals, "tools": recipe.get("tools") or [], "notes": list(recipe.get("notes") or [])}


def recipe_shopping_embed(result: dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(
        title=f"🧮 Shopping list: {result['recipe']}",
        description=f"**Table:** {result['table']}\n**Batches:** {result['batches']}\nRepeated ingredient rows are added together for the total.",
        color=discord.Color.from_rgb(57, 75, 111),
    )
    lines = [f"• **{name}** ×{quantity}" for name, quantity in result["ingredients"].items()]
    text = "\n".join(lines) or "No ingredients recorded."
    if len(text) > 3900:
        text = text[:3850] + "\n… list truncated; use the exports for the complete data."
    embed.add_field(name="Total ingredients required", value=text, inline=False)
    if result["tools"]:
        embed.add_field(name="Tools (not consumed)", value=", ".join(result["tools"])[:1024], inline=False)
    if result.get("notes"):
        embed.add_field(name="Data review notes", value="\n".join(f"• {note}" for note in result["notes"])[:1024], inline=False)
    return embed


def table_ingredient_sets(data: dict[str, Any]):
    tables = {}
    display_names = {}
    for table in data.get("tables", []):
        names = set()
        for recipe in table.get("recipes", []):
            for ingredient, _quantity in recipe.get("ingredients") or []:
                key = str(ingredient).casefold().strip()
                if key:
                    names.add(key)
                    display_names.setdefault(key, str(ingredient).strip())
        tables[table.get("name", "Unnamed table")] = names
    return tables, display_names


def table_comparison_embed(data: dict[str, Any]) -> discord.Embed:
    tables, display_names = table_ingredient_sets(data)
    counts = Counter(key for names in tables.values() for key in names)
    shared = sorted((display_names[k] for k, count in counts.items() if count > 1), key=str.casefold)
    embed = discord.Embed(
        title="⚖️ Crafting Table Comparison",
        description=f"**{len(tables)} tables** · **{len(counts)} distinct ingredient names** · **{len(shared)} shared across multiple tables**\nNames are compared case-insensitively; different words/plurals remain separate.",
        color=discord.Color.from_rgb(57, 75, 111),
    )
    table_items = list(tables.items())
    for table_name, names in table_items[:6]:
        exclusive = sorted((display_names[k] for k in names if counts[k] == 1), key=str.casefold)
        shared_here = sorted((display_names[k] for k in names if counts[k] > 1), key=str.casefold)
        lines = [
            f"**Ingredients:** {len(names)} · **Shared:** {len(shared_here)} · **Exclusive:** {len(exclusive)}",
            "Exclusive: " + (", ".join(exclusive[:8]) if exclusive else "None"),
        ]
        if len(exclusive) > 8:
            lines.append(f"…and {len(exclusive) - 8} more exclusive ingredients")
        embed.add_field(name=table_name[:256], value="\n".join(lines)[:500], inline=False)
    if shared:
        embed.add_field(name="Most shared ingredients", value=", ".join(shared[:16])[:600], inline=False)
    if len(table_items) > 6:
        embed.set_footer(text=f"Showing 6 of {len(table_items)} tables. Export the directory for complete details.")
    return embed


def validate_recipe_data(data: dict[str, Any]):
    """Return cautious findings; never auto-correct or merge user-authored data."""
    findings = []
    if not isinstance(data, dict) or not isinstance(data.get("tables"), list):
        return [{"severity": "error", "message": "Recipe data must be an object containing a tables list."}]
    ingredient_locations = defaultdict(list)
    seen_table_names = set()
    for table_index, table in enumerate(data["tables"], start=1):
        if not isinstance(table, dict):
            findings.append({"severity": "error", "message": f"Table entry {table_index} is not an object."})
            continue
        raw_table_name = table.get("name", "")
        table_name = raw_table_name.strip() if isinstance(raw_table_name, str) else ""
        if not table_name:
            findings.append({"severity": "error", "message": f"Table entry {table_index} needs a non-empty string name."})
        elif table_name.casefold() in seen_table_names:
            findings.append({"severity": "warning", "message": f"More than one crafting table is named '{table_name}'."})
        seen_table_names.add(table_name.casefold())
        recipes = table.get("recipes", [])
        if not isinstance(recipes, list):
            findings.append({"severity": "error", "message": f"{table_name or 'Unnamed table'}: recipes must be a list."})
            continue
        seen_recipe_names = set()
        for recipe_index, recipe in enumerate(recipes, start=1):
            if not isinstance(recipe, dict):
                findings.append({"severity": "error", "message": f"{table_name}: recipe entry {recipe_index} is not an object."})
                continue
            raw_recipe_name = recipe.get("name", "")
            recipe_name = raw_recipe_name.strip() if isinstance(raw_recipe_name, str) else ""
            if not recipe_name:
                findings.append({"severity": "error", "message": f"{table_name}: recipe entry {recipe_index} needs a non-empty string name."})
            folded_recipe = recipe_name.casefold()
            if folded_recipe and folded_recipe in seen_recipe_names:
                findings.append({"severity": "warning", "message": f"{table_name}: more than one recipe is named '{recipe_name}'."})
            seen_recipe_names.add(folded_recipe)
            ingredients = recipe.get("ingredients", [])
            if not isinstance(ingredients, list):
                findings.append({"severity": "error", "message": f"{table_name} / {recipe_name or 'Unnamed recipe'}: ingredients must be a list."})
                continue
            if not ingredients:
                findings.append({"severity": "warning", "message": f"{table_name} / {recipe_name or 'Unnamed recipe'}: no ingredients are recorded."})
            seen_recipe_ingredients = set()
            for item in ingredients:
                if not isinstance(item, (list, tuple)) or len(item) != 2:
                    findings.append({"severity": "error", "message": f"{table_name} / {recipe_name}: malformed ingredient entry {item!r}."})
                    continue
                name, quantity = item
                label = name.strip() if isinstance(name, str) else ""
                if not label:
                    findings.append({"severity": "error", "message": f"{table_name} / {recipe_name}: ingredient name must be a non-empty string."})
                    continue
                folded_ingredient = label.casefold()
                if folded_ingredient in seen_recipe_ingredients:
                    findings.append({"severity": "warning", "message": f"{table_name} / {recipe_name}: '{label}' appears more than once in the ingredient list. Confirm whether the rows should be combined; no quantities were changed."})
                seen_recipe_ingredients.add(folded_ingredient)
                valid_quantity = (
                    isinstance(quantity, int) and not isinstance(quantity, bool) and quantity >= 1
                ) or (
                    isinstance(quantity, str) and quantity.isdigit() and int(quantity) >= 1
                )
                if not valid_quantity:
                    findings.append({"severity": "error", "message": f"{table_name} / {recipe_name}: '{label}' has an invalid quantity ({quantity!r})."})
                ingredient_locations[label.casefold()].append((label, table_name, recipe_name))
    distinct = {}
    for entries in ingredient_locations.values():
        if entries:
            distinct.setdefault(entries[0][0], None)
    names = list(distinct)
    comparisons = 0
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            comparisons += 1
            if comparisons > 50000:
                findings.append({"severity": "warning", "message": "Spelling-variation scan was capped at 50,000 comparisons for performance; other validation checks completed."})
                break
            if left.casefold() == right.casefold():
                continue
            if SequenceMatcher(None, left.casefold(), right.casefold()).ratio() >= 0.75:
                findings.append({"severity": "warning", "message": f"Possible spelling variation: '{left}' vs '{right}'. Review manually; neither name was changed."})
        if comparisons > 50000:
            break
    # Cross-reference ingredient names against recipe outputs. Unmatched names are
    # informational only: many are intentionally gathered or purchased raw materials.
    recipe_outputs = defaultdict(list)
    for table in data["tables"]:
        if not isinstance(table, dict) or not isinstance(table.get("recipes", []), list):
            continue
        for recipe in table.get("recipes", []):
            if not isinstance(recipe, dict):
                continue
            output_name = recipe.get("name", "")
            if isinstance(output_name, str) and output_name.strip():
                recipe_outputs[output_name.strip().casefold()].append((table.get("name", "Unknown table"), output_name.strip()))

    unmatched = []
    for folded_name, entries in ingredient_locations.items():
        if folded_name not in recipe_outputs and entries:
            display_name = entries[0][0]
            locations = sorted({f"{table} / {recipe}" for _, table, recipe in entries})
            unmatched.append((display_name, len(locations), locations[:2]))
    if unmatched:
        findings.append({
            "severity": "info",
            "message": f"{len(unmatched)} ingredient name(s) are not exact recipe outputs. This is normal for raw materials; examples: "
                + "; ".join(f"{name} ({count} recipe location(s))" for name, count, _ in unmatched[:6])
                + ". Check only if you expected one of these items to be made at another table.",
        })

    duplicate_outputs = [(name, places) for name, places in recipe_outputs.items() if len(places) > 1]
    if duplicate_outputs:
        examples = []
        for folded_name, places in duplicate_outputs[:6]:
            display_name = places[0][1]
            tables = sorted({table for table, _ in places})
            examples.append(f"{display_name} ({', '.join(tables)})")
        findings.append({
            "severity": "info",
            "message": f"{len(duplicate_outputs)} recipe output name(s) are produced by multiple recipes/tables. These may be intentional alternatives; examples: "
                + "; ".join(examples) + ".",
        })

    if not findings:
        findings.append({"severity": "success", "message": "No obvious recipe-data issues found."})
    return findings


def validation_embed(findings: list[dict[str, str]]) -> discord.Embed:
    counts = Counter(item["severity"] for item in findings)
    embed = discord.Embed(
        title="🧪 Recipe Data Check",
        description=f"**{counts['error']} error(s)** · **{counts['warning']} warning(s)** · **{counts['success']} clean result(s)**\nThis checker never changes recipe data.",
        color=discord.Color.orange() if counts["error"] or counts["warning"] else discord.Color.green(),
    )
    for item in findings[:10]:
        icon = {"error": "🔴", "warning": "🟠", "info": "🔵", "success": "🟢"}.get(item["severity"], "ℹ️")
        embed.add_field(name=f"{icon} {item['severity'].title()}", value=item["message"][:400], inline=False)
    if len(findings) > 10:
        embed.set_footer(text=f"Showing 10 of {len(findings)} findings. Review the full export for additional flagged entries.")
    return embed


def recipes_csv_bytes(data: dict[str, Any]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["Crafting Table", "Recipe", "Ingredient", "Quantity", "Occurrence"])
    for table in data.get("tables", []):
        for recipe in table.get("recipes", []):
            for occurrence, (ingredient, quantity) in enumerate(recipe.get("ingredients") or [], start=1):
                writer.writerow([table.get("name", ""), recipe.get("name", ""), ingredient, quantity, occurrence])
    return stream.getvalue().encode("utf-8-sig")


def recipes_xlsx_bytes(data: dict[str, Any]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Ingredients"
    sheet.append(["Crafting Table", "Recipe", "Ingredient", "Quantity", "Occurrence"])
    for table in data.get("tables", []):
        for recipe in table.get("recipes", []):
            for occurrence, (ingredient, quantity) in enumerate(recipe.get("ingredients") or [], start=1):
                sheet.append([table.get("name", ""), recipe.get("name", ""), ingredient, quantity, occurrence])
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="394B6F")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column, width in {"A": 24, "B": 28, "C": 30, "D": 12, "E": 14}.items():
        sheet.column_dimensions[column].width = width
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


# --- Crafting Explorer and Planner extensions ---

def ensure_stable_ids(data: dict[str, Any], persistable: bool = True):
    """Add stable IDs without changing ingredient rows or names."""
    import uuid
    namespace = uuid.UUID("a03e62a5-21f4-49a5-92de-92b9b94a7a6e")
    for ti, table in enumerate(data.get("tables", [])):
        if not table.get("id"):
            table["id"] = str(uuid.uuid5(namespace, f"table:{ti}:{table.get('name','')}"))
        for ri, recipe in enumerate(table.get("recipes", [])):
            if not recipe.get("id"):
                recipe["id"] = str(uuid.uuid5(namespace, f"recipe:{table['id']}:{ri}:{recipe.get('name','')}"))
    return data


def dependency_chain(data: dict[str, Any], item_name: str, max_depth: int = 8):
    """Trace recipe outputs backward to their ingredient recipes, safely stopping cycles."""
    ensure_stable_ids(data)
    by_output = {}
    for table in data.get("tables", []):
        for recipe in table.get("recipes", []):
            by_output.setdefault(_normalize_chat_search(str(recipe.get("name", ""))), []).append((table, recipe))
    visited = set()
    def walk(item, depth):
        key = _normalize_chat_search(str(item))
        if not key or depth >= max_depth or key in visited:
            return {"item": item, "cycle": key in visited, "recipes": []}
        visited.add(key)
        matches = []
        for table, recipe in by_output.get(key, []):
            ingredients = []
            for name, qty in recipe.get("ingredients") or []:
                ingredients.append({"name": str(name), "quantity": int(qty), "source": walk(name, depth + 1)})
            matches.append({"table": table.get("name", ""), "recipe": recipe.get("name", ""), "ingredients": ingredients, "notes": list(recipe.get("notes") or [])})
        visited.remove(key)
        return {"item": item, "cycle": False, "recipes": matches}
    return walk(item_name, 0)


def dependency_lines(node, depth=0, limit=60):
    lines = []
    prefix = "  " * min(depth, 8)
    if node.get("cycle"):
        return [f"{prefix}↳ {node['item']} (cycle stopped)"]
    recipes = node.get("recipes") or []
    if not recipes:
        return [f"{prefix}• {node['item']} (no recipe output found; treated as base item)"]
    for entry in recipes:
        lines.append(f"{prefix}🛠️ {entry['recipe']} — {entry['table']}")
        lines.extend(f"{prefix}  ⚠️ {note}" for note in entry.get("notes", []))
        for ingredient in entry["ingredients"]:
            lines.append(f"{prefix}  • {ingredient['name']} ×{ingredient['quantity']}")
            lines.extend(dependency_lines(ingredient["source"], depth + 2, limit)[:max(0, limit-len(lines))])
            if len(lines) >= limit:
                lines.append("… dependency view shortened")
                return lines
    return lines


def parse_inventory(text: str):
    """Parse an inventory string, retaining repeated rows until totals are calculated."""
    from collections import defaultdict
    totals = defaultdict(int)
    for name, quantity in parse_simple_items(text):
        totals[name] += quantity
    return dict(totals)


def parse_simple_items(text: str):
    import re
    parsed = []
    for part in re.split(r"[,;\n]+", text or ""):
        item = part.strip()
        if not item:
            continue
        match = re.match(r"^(.*?)\s+[x×]\s*(\d+)$", item, re.IGNORECASE)
        if match:
            name, quantity = match.group(1).strip(), int(match.group(2))
        else:
            quantity_first = re.match(r"^([0-9][0-9,]*)\s*(?:[x×]\s*)+(.+)$", item, re.IGNORECASE)
            if not quantity_first:
                quantity_first = re.match(r"^([0-9][0-9,]*)\s+([A-Za-z].+)$", item)
            if quantity_first:
                quantity, name = int(quantity_first.group(1).replace(",", "")), quantity_first.group(2).strip()
            else:
                name, quantity = item, 1
        if not name or quantity < 1:
            raise ValueError(f"Invalid inventory entry: {item}")
        parsed.append((name, quantity))
    if not parsed:
        raise ValueError("Enter at least one item, for example: Plastic x5, Wire x10")
    return parsed



def inventory_quantity(stock: dict[str, int], item_name: str) -> int:
    """Read inventory quantities case-insensitively and with spaces/punctuation normalized."""
    target = _normalize_chat_search(item_name)
    return sum(
        int(quantity)
        for name, quantity in stock.items()
        if _normalize_chat_search(name) == target
    )


def calculate_inventory_limited_batches(
    data: dict[str, Any],
    recipe_query: str,
    inventory_text: str,
):
    """Estimate batches of one saved recipe from the quantities the player lists.

    A batch limit is calculated from only the supplied stock items that are
    ingredients in the selected recipe. Other ingredients are then reported as
    additional requirements, rather than silently assumed to be available.
    """
    stock = parse_inventory(inventory_text)
    matches = chat_recipe_search(data, recipe_query, limit=25)
    exact = [item for item in matches if item.get("score", 0) >= 0.94]
    stock_names = {_normalize_chat_search(name) for name in stock}
    viable = [
        item for item in exact
        if any(_normalize_chat_search(name) in stock_names for name, _ in item.get("ingredients", []))
    ]
    if not viable:
        return None
    if len(viable) > 1:
        choices = sorted(
            {f"{item.get('recipe', 'Unknown')} — {item.get('table', 'Unknown table')}" for item in viable},
            key=str.casefold,
        )
        return {"error": "I found multiple saved recipes that use those items. Choose the table/recipe: " + "; ".join(choices[:8])}

    selected = viable[0]
    per_batch = {}
    for name, quantity in selected.get("ingredients", []):
        per_batch[name] = per_batch.get(name, 0) + int(quantity)
    limits = [
        inventory_quantity(stock, name) // quantity
        for name, quantity in per_batch.items()
        if inventory_quantity(stock, name) > 0 and quantity > 0
    ]
    if not limits:
        return None
    batches = min(limits)
    planned_batches = max(1, batches)
    required = {name: quantity * planned_batches for name, quantity in per_batch.items()}
    missing = {
        name: max(0, quantity - inventory_quantity(stock, name))
        for name, quantity in required.items()
        if inventory_quantity(stock, name) < quantity
    }
    return {
        "recipe": selected.get("recipe", "Unknown"),
        "table": selected.get("table", "Unknown table"),
        "batches": batches,
        "planned_batches": planned_batches,
        "stock_used": {
            name: min(inventory_quantity(stock, name), quantity)
            for name, quantity in required.items()
            if inventory_quantity(stock, name) > 0
        },
        "required": required,
        "missing": missing,
        "tools": list(selected.get("tools") or []),
        "notes": list(selected.get("notes") or []),
    }


def inventory_plan(data: dict[str, Any], table_name: str, recipe_name: str, target_batches: int, inventory_text: str):
    if not isinstance(target_batches, int) or not 1 <= target_batches <= 999:
        raise ValueError("Target batches must be between 1 and 999.")
    recipe_result = calculate_recipe_ingredients(data, table_name, recipe_name, target_batches)
    required = recipe_result["ingredients"]
    stock = parse_inventory(inventory_text)
    available_batches = None
    for name, per_target in required.items():
        per_batch = per_target // target_batches
        possible = inventory_quantity(stock, name) // per_batch if per_batch else 999
        available_batches = possible if available_batches is None else min(available_batches, possible)
    available_batches = available_batches or 0
    missing = {name: max(0, quantity-inventory_quantity(stock, name)) for name, quantity in required.items() if inventory_quantity(stock, name) < quantity}
    return {"available_batches": min(available_batches, 999), "target_batches": target_batches, "required": required, "stock": stock, "missing": missing, "notes": recipe_result.get("notes", [])}


def expanded_production_requirements(
    data: dict[str, Any],
    table_name: str,
    recipe_name: str,
    batches: int = 1,
    max_depth: int = 8,
):
    """Expand a recipe into base ingredients, multiplying every nested batch.

    Only a uniquely named producer is expanded automatically. Ambiguous outputs
    remain listed as ingredients with an explanation instead of guessing a table.
    """
    if not isinstance(batches, int) or not 1 <= batches <= 999:
        raise ValueError("Batch count must be between 1 and 999.")
    if not isinstance(max_depth, int) or not 1 <= max_depth <= 12:
        raise ValueError("Production depth must be between 1 and 12.")
    target = calculate_recipe_ingredients(data, table_name, recipe_name, 1)
    target_table = next(t for t in data.get("tables", []) if t.get("name", "").casefold().strip() == table_name.casefold().strip())
    target_recipe = next(r for r in target_table.get("recipes", []) if r.get("name", "").casefold().strip() == recipe_name.casefold().strip())

    producers = defaultdict(list)
    for table in data.get("tables", []):
        for recipe in table.get("recipes", []):
            key = str(recipe.get("name", "")).casefold().strip()
            if key:
                producers[_normalize_chat_search(str(recipe.get("name", "")))].append((table, recipe))

    base_totals = defaultdict(int)
    expanded = []
    tools = set()
    notes = []

    def expand(table, recipe, multiplier, depth, stack):
        label = f"{table.get('name', 'Unknown table')} — {recipe.get('name', 'Unknown recipe')}"
        expanded.append({"table": table.get("name", "Unknown table"), "recipe": recipe.get("name", "Unknown recipe"), "batches": multiplier})
        tools.update(str(tool) for tool in (recipe.get("tools") or []) if str(tool).strip())
        notes.extend(str(note) for note in (recipe.get("notes") or []) if str(note).strip())
        for ingredient_name, quantity in recipe.get("ingredients") or []:
            amount = int(quantity) * multiplier
            key = _normalize_chat_search(str(ingredient_name))
            options = producers.get(key, [])
            if key in stack:
                base_totals[str(ingredient_name)] += amount
                notes.append(f"Cycle stopped at {ingredient_name} while expanding {label}; kept it as a base requirement.")
            elif depth >= max_depth:
                base_totals[str(ingredient_name)] += amount
                notes.append(f"Depth limit reached at {ingredient_name}; kept it as a base requirement.")
            elif len(options) == 1:
                next_table, next_recipe = options[0]
                expand(next_table, next_recipe, amount, depth + 1, stack | {key})
            elif len(options) > 1:
                base_totals[str(ingredient_name)] += amount
                choices = ", ".join(f"{t.get('name', 'Unknown table')} / {r.get('name', 'Unknown recipe')}" for t, r in options[:4])
                notes.append(f"{ingredient_name} has multiple possible producers ({choices}); left unexpanded.")
            else:
                base_totals[str(ingredient_name)] += amount

    expand(target_table, target_recipe, batches, 0, {_normalize_chat_search(str(target_recipe.get("name", "")))})
    return {
        "table": target["table"],
        "recipe": target["recipe"],
        "batches": batches,
        "base_ingredients": dict(base_totals),
        "expanded_recipes": expanded,
        "tools": sorted(tools, key=str.casefold),
        "notes": list(dict.fromkeys(notes)),
    }


def multi_recipe_plan(data: dict[str, Any], requests: list[tuple[str, str, int]]):
    if not requests:
        raise ValueError("Enter at least one table, recipe, and batch-count line.")
    from collections import defaultdict
    totals = defaultdict(int)
    tools = set()
    notes = []
    selected = []
    for table, recipe, batches in requests:
        result = calculate_recipe_ingredients(data, table, recipe, batches)
        selected.append(f"{result['table']} — {result['recipe']} ×{batches}")
        for name, quantity in result["ingredients"].items():
            totals[name] += quantity
        tools.update(result["tools"])
        notes.extend(result.get("notes", []))
    return {"selected": selected, "ingredients": dict(totals), "tools": sorted(tools, key=str.casefold), "notes": list(dict.fromkeys(notes))}


def advanced_search(data: dict[str, Any], query: str = "", table_filter: str = "", ingredient_filter: str = "", tool_filter: str = "", min_ingredients: int = 0):
    if not isinstance(min_ingredients, int) or not 0 <= min_ingredients <= 999:
        raise ValueError("Minimum ingredient rows must be between 0 and 999.")
    results = []
    for table, recipe in ((t, r) for t in data.get("tables", []) for r in t.get("recipes", [])):
        ingredients = recipe.get("ingredients") or []
        tools = recipe.get("tools") or []
        if table_filter and table_filter.casefold() not in table.get("name", "").casefold():
            continue
        if ingredient_filter and not any(ingredient_filter.casefold() in str(x[0]).casefold() for x in ingredients):
            continue
        if tool_filter and not any(tool_filter.casefold() in str(x).casefold() for x in tools):
            continue
        if len(ingredients) < min_ingredients:
            continue
        haystack = " ".join([table.get("name", ""), recipe.get("name", "")] + [str(x[0]) for x in ingredients] + [str(x) for x in tools]).casefold()
        if query and query.casefold() not in haystack:
            continue
        results.append((table.get("name", ""), recipe))
    return results


def recipe_comparison(data: dict[str, Any], table_a: str, recipe_a: str, table_b: str, recipe_b: str):
    a = calculate_recipe_ingredients(data, table_a, recipe_a, 1)
    b = calculate_recipe_ingredients(data, table_b, recipe_b, 1)
    left = {str(k).casefold(): (k, v) for k, v in a["ingredients"].items()}
    right = {str(k).casefold(): (k, v) for k, v in b["ingredients"].items()}
    common = sorted((left[k][0] for k in left.keys() & right.keys()), key=str.casefold)
    only_a = sorted((left[k][0] for k in left.keys() - right.keys()), key=str.casefold)
    only_b = sorted((right[k][0] for k in right.keys() - left.keys()), key=str.casefold)
    return {"a": a, "b": b, "shared": common, "only_a": only_a, "only_b": only_b}


def validate_import_structure(incoming: dict[str, Any]):
    """Reject malformed JSON structures before merge; preserve all valid ingredient rows."""
    if not isinstance(incoming, dict) or not isinstance(incoming.get("tables"), list):
        raise ValueError("Import must be a JSON object containing a tables list.")
    for ti, table in enumerate(incoming["tables"], start=1):
        if not isinstance(table, dict):
            raise ValueError(f"Table entry {ti} must be an object.")
        name = table.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Table entry {ti} needs a non-empty string name.")
        recipes = table.get("recipes", [])
        if not isinstance(recipes, list):
            raise ValueError(f"Table '{name}' recipes must be a list.")
        for ri, recipe in enumerate(recipes, start=1):
            if not isinstance(recipe, dict):
                raise ValueError(f"Recipe {ri} in '{name}' must be an object.")
            recipe_name = recipe.get("name")
            if not isinstance(recipe_name, str) or not recipe_name.strip():
                raise ValueError(f"Recipe {ri} in '{name}' needs a non-empty string name.")
            ingredients = recipe.get("ingredients", [])
            if not isinstance(ingredients, list):
                raise ValueError(f"{name} / {recipe_name}: ingredients must be a list.")
            for ii, ingredient in enumerate(ingredients, start=1):
                if not isinstance(ingredient, (list, tuple)) or len(ingredient) != 2:
                    raise ValueError(f"{name} / {recipe_name}: ingredient row {ii} must be [name, quantity].")
                item_name, quantity = ingredient
                if not isinstance(item_name, str) or not item_name.strip():
                    raise ValueError(f"{name} / {recipe_name}: ingredient row {ii} has a blank name.")
                if isinstance(quantity, bool):
                    raise ValueError(f"{name} / {recipe_name}: ingredient row {ii} quantity must be a positive integer.")
                try:
                    parsed_quantity = int(quantity)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ValueError(f"{name} / {recipe_name}: ingredient row {ii} quantity must be a positive integer.") from exc
                if parsed_quantity < 1 or str(parsed_quantity) != str(quantity).strip():
                    raise ValueError(f"{name} / {recipe_name}: ingredient row {ii} quantity must be a positive integer.")
            tools = recipe.get("tools", [])
            if not isinstance(tools, list) or any(not isinstance(tool, str) for tool in tools):
                raise ValueError(f"{name} / {recipe_name}: tools must be a list of strings.")
    return True


def merge_recipe_import(current: dict[str, Any], incoming: dict[str, Any], mode: str = "skip"):
    """Merge validated recipe data; name conflicts are skipped or replaced only by explicit choice."""
    if mode not in {"skip", "replace"}:
        raise ValueError("Conflict mode must be skip or replace.")
    validate_import_structure(incoming)
    validate_import_structure(current)
    import copy
    incoming_copy = copy.deepcopy(incoming)
    result = copy.deepcopy(current)
    ensure_stable_ids(result)
    ensure_stable_ids(incoming_copy)
    added_tables = added_recipes = skipped = replaced = 0
    for new_table in incoming_copy["tables"]:
        table_key = new_table["name"].casefold().strip()
        target = next((t for t in result["tables"] if t["name"].casefold().strip() == table_key), None)
        if target is None:
            result["tables"].append(new_table)
            added_tables += 1
            added_recipes += len(new_table.get("recipes", []))
            continue
        for new_recipe in new_table.get("recipes", []):
            recipe_key = new_recipe["name"].casefold().strip()
            existing = next((r for r in target.get("recipes", []) if r["name"].casefold().strip() == recipe_key), None)
            if existing is None:
                target.setdefault("recipes", []).append(new_recipe)
                added_recipes += 1
            elif mode == "replace":
                new_recipe["id"] = existing.get("id", new_recipe.get("id"))
                target["recipes"][target["recipes"].index(existing)] = new_recipe
                replaced += 1
            else:
                skipped += 1
    findings = validate_recipe_data(result)
    errors = [f for f in findings if f["severity"] == "error"]
    if errors:
        raise ValueError("Import validation failed: " + "; ".join(x["message"] for x in errors[:5]))
    return result, {"tables_added": added_tables, "recipes_added": added_recipes, "skipped": skipped, "replaced": replaced, "warnings": sum(x["severity"] == "warning" for x in findings)}


def analytics_embed(data: dict[str, Any], stats: dict[str, Any]):
    embed = discord.Embed(title="📈 Crafting Analytics", color=discord.Color.from_rgb(57, 75, 111))
    total = sum(len(t.get("recipes", [])) for t in data.get("tables", []))
    embed.description = f"**{len(data.get('tables', []))} tables** · **{total} recipes** · **{sum(len(r.get('ingredients') or []) for t in data.get('tables', []) for r in t.get('recipes', []))} ingredient rows**"
    embed.add_field(name="Menu opens", value=str(stats.get("commands", 0)))
    embed.add_field(name="Searches", value=str(stats.get("searches", 0)))
    top_tables = sorted(stats.get("tables", {}).items(), key=lambda x: x[1], reverse=True)[:8]
    embed.add_field(name="Most browsed tables", value="\n".join(f"• {name}: {count}" for name, count in top_tables) or "No usage recorded.", inline=False)
    top_terms = sorted(stats.get("terms", {}).items(), key=lambda x: x[1], reverse=True)[:8]
    embed.add_field(name="Popular searches", value="\n".join(f"• {name}: {count}" for name, count in top_terms) or "No searches recorded.", inline=False)
    embed.add_field(name="Unmatched searches", value=str(stats.get("no_results", 0)))
    top_misses = sorted(stats.get("no_result_terms", {}).items(), key=lambda x: x[1], reverse=True)[:8]
    embed.add_field(name="Searches needing better matches", value="\n".join(f"• {name}: {count}" for name, count in top_misses) or "No unmatched searches recorded.", inline=False)
    return embed


def item_cross_reference(data: dict[str, Any], query: str, shop_catalog=None):
    """Join an item across saved recipe outputs, ingredients, tools and shop listings."""
    catalog = SHOP_PRICE_CATALOG if shop_catalog is None else shop_catalog
    needle = _normalize_chat_search(query)
    if not needle:
        return {"error": "Enter an item name, for example !item Filter Paper."}

    candidates = {}
    def add_candidate(name, kind, details=None, aliases=()):
        label = str(name or "").strip()
        if not label:
            return
        key = _normalize_chat_search(label)
        if not key:
            return
        entry = candidates.setdefault(key, {"name": label, "aliases": set(), "kinds": set()})
        entry["kinds"].add(kind)
        for alias in aliases or ():
            alias_key = _normalize_chat_search(alias)
            if alias_key:
                entry["aliases"].add(alias_key)

    for table in data.get("tables", []):
        if not isinstance(table, dict):
            continue
        for recipe in table.get("recipes", []):
            if not isinstance(recipe, dict):
                continue
            add_candidate(recipe.get("name"), "output")
            for ingredient, _quantity in recipe.get("ingredients") or []:
                add_candidate(ingredient, "ingredient")
            for tool in recipe.get("tools") or []:
                add_candidate(tool, "tool")

    for item in catalog:
        add_candidate(item.get("name"), "shop", aliases=item.get("aliases", ()))

    scored = []
    for key, entry in candidates.items():
        names = {key, *entry["aliases"]}
        score = max(
            1.0 if needle == name else
            0.96 if needle in name or name in needle else
            _fuzzy_name_score(needle, name)
            for name in names
        )
        if score >= (0.76 if len(needle.replace(" ", "")) <= 5 else 0.68):
            scored.append((score, key, entry))
    if not scored:
        return {"error": f"I couldn't find **{query}** in saved recipes, tools, or shop listings. I won't guess."}

    scored.sort(key=lambda row: (-row[0], row[2]["name"].casefold()))
    best_score = scored[0][0]
    best = [row for row in scored if abs(row[0] - best_score) < 0.0001]
    if len(best) > 1:
        return {"suggestions": [row[2]["name"] for row in best[:8]]}

    _score, matched_key, entry = best[0]
    item_name = entry["name"]
    result = {"item": item_name, "produced_by": [], "used_in": [], "required_as_tool": [], "shops": []}
    for table in data.get("tables", []):
        if not isinstance(table, dict):
            continue
        table_name = str(table.get("name", "Unknown table"))
        for recipe in table.get("recipes", []):
            if not isinstance(recipe, dict):
                continue
            recipe_name = str(recipe.get("name", "Unknown recipe"))
            if _normalize_chat_search(recipe_name) == matched_key:
                result["produced_by"].append({"table": table_name, "recipe": recipe_name})
            for ingredient, quantity in recipe.get("ingredients") or []:
                if _normalize_chat_search(ingredient) == matched_key:
                    result["used_in"].append({"table": table_name, "recipe": recipe_name, "quantity": quantity})
            if any(_normalize_chat_search(tool) == matched_key for tool in recipe.get("tools") or []):
                result["required_as_tool"].append({"table": table_name, "recipe": recipe_name})
    for item in catalog:
        item_key = _normalize_chat_search(item.get("name"))
        alias_keys = {_normalize_chat_search(alias) for alias in item.get("aliases", ())}
        if item_key == matched_key or matched_key in alias_keys:
            result["shops"].append({
                "shop": item.get("shop", "Shop not recorded"),
                "price": item.get("price"),
            })
    return result


def validate_city_reference_data(data: dict[str, Any], shop_catalog=None):
    """Review cross-reference coverage and shop catalogue consistency without changing data."""
    catalog = SHOP_PRICE_CATALOG if shop_catalog is None else shop_catalog
    findings = []
    alias_owners = defaultdict(set)
    seen_items = set()
    for index, item in enumerate(catalog, start=1):
        if not isinstance(item, dict):
            findings.append({"severity": "error", "message": f"Shop catalogue entry {index} is not an object."})
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            findings.append({"severity": "error", "message": f"Shop catalogue entry {index} has no item name."})
            continue
        key = _normalize_chat_search(name)
        if key in seen_items:
            findings.append({"severity": "warning", "message": f"Shop catalogue contains a repeated item name: '{name}'."})
        seen_items.add(key)
        price = item.get("price")
        if not isinstance(price, int) or isinstance(price, bool) or price < 0:
            findings.append({"severity": "error", "message": f"'{name}' has a missing or invalid shop price."})
        for alias in [name, *(item.get("aliases") or ())]:
            alias_key = _normalize_chat_search(alias)
            if alias_key:
                alias_owners[alias_key].add(name)
    collisions = [(alias, sorted(owners)) for alias, owners in alias_owners.items() if len(owners) > 1]
    for alias, owners in collisions[:20]:
        findings.append({"severity": "warning", "message": f"Shop search alias '{alias}' points to multiple items: {', '.join(owners)}. Review manually; no names were changed."})

    ingredient_names = set()
    for table in (data or {}).get("tables", []):
        if not isinstance(table, dict):
            continue
        for recipe in table.get("recipes", []):
            if not isinstance(recipe, dict):
                continue
            for ingredient, _quantity in recipe.get("ingredients") or []:
                key = _normalize_chat_search(ingredient)
                if key:
                    ingredient_names.add(key)
    known_shop_names = set(alias_owners)
    not_listed = sorted(name for name in ingredient_names if name not in known_shop_names)
    if not_listed:
        findings.append({
            "severity": "info",
            "message": f"{len(not_listed)} recipe ingredient name(s) have no matching shop-price entry. This may be intentional for collected, produced, or otherwise unpriced items. Examples: {', '.join(not_listed[:10])}.",
        })
    if not findings:
        findings.append({"severity": "success", "message": "No obvious shop catalogue or cross-reference issues found."})
    return findings[:40]
