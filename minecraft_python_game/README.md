# PyCraft — Voxel Survival Sandbox in Python

An original, playable 3D Minecraft-inspired voxel survival sandbox game written in Python using the **Ursina Engine (Panda3D)**, **NumPy**, and **Pillow**.

All textures, icons, GUI widgets, sound effects, and 3D models are generated procedurally as original
Minecraft-*style* pixel art — no external or proprietary assets are required.

---

## 1. Python Version

- **Python 3.10+** (Tested on **Python 3.10 – 3.13**)
- Cross-platform: runs on Windows, macOS, and Linux.

---

## 2. Installation Command

Unpack `minecraft_python_game.zip` (or clone/open the project directory) and navigate into the project folder:

```bash
unzip minecraft_python_game.zip -d pycraft
cd pycraft
```

---

## 3. How to Install Dependencies

Create an optional virtual environment and install the required packages from `requirements.txt`:

```bash
python3 -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

---

## 4. How to Launch the Game

Run `main.py` with Python:

```bash
python3 main.py
```

*(Note: If running in a headless CI/container environment without an X11/Wayland display, you can run `python3 main.py --headless` or `xvfb-run -a python3 main.py`.)*

---

## 5. Controls

| Input | Action |
| :--- | :--- |
| **W / S / A / D** | Walk Forward / Backward / Strafe Left / Strafe Right |
| **Shift** (hold) | Sprint (faster, FOV kick, consumes slightly more hunger) |
| **Space** | Jump (or Swim Upward while in water) |
| **Mouse** | First-person camera look (with Minecraft-style view bobbing) |
| **Left Mouse** (hold) | Break targeted block (destroy-stage crack overlay) or melee attack a mob |
| **Right Mouse** | Place block, open Crafting Table / Furnace, or eat held food |
| **1 – 9** | Select Hotbar slot |
| **Mouse Wheel** | Cycle Hotbar slot selection |
| **E** | Open / Close the Inventory & Crafting screen |
| **F** | Eat currently selected food |
| **Esc** | Pause Menu / close open screen |

Inside the inventory screen: **left click** picks up / places / swaps a stack, **right click** splits or
places a single item, the cursor stack follows the mouse, and hovering a slot shows a tooltip.
The **Recipes** button opens the recipe book — clicking a recipe moves its ingredients straight
into the crafting grid (2x2 in your inventory, 3x3 at a Crafting Table).

---

## 6. Minecraft-Style Rework Highlights

- **Faithful 16x16 pixel-art block atlas**: grass (top/side fringe), dirt, stone, voronoi cobblestone,
  oak & **birch logs**, leaves, sand, gravel, water, glass, wool, ores with blob clusters, planks,
  crafting table, furnace (+ lit fire mouth), chest, torch, bedrock, plus 5 **destroy-stage crack
  overlays** and the black block-selection outline.
- **Minecraft GUI widget sheet**: sunken slots, 9-slot hotbar with white selection highlight,
  heart & hunger icon rows (full / half / empty), green **experience bar + level number**,
  crosshair, beveled buttons, furnace flame & progress arrow, and the classic gray beveled
  container window for Inventory / Crafting Table / Furnace screens.
- **Isometric block item icons** and hand-drawn 16x16 tool / food / material icons
  (pickaxes, axes, swords in wood/stone/iron/diamond, apple, porkchops, steak, ingots, gems...).
- **Animated first-person viewmodel**: bare arm + hand like the reference screenshots, swing arc
  when mining/attacking, eating wiggle, walking bob synced with camera view-bobbing, sprint FOV kick.
- **Textured articulated mobs** with joint-based walk animations: Pig, Cow, **Sheep**, Zombie
  (arms forward), Skeleton, and **Creeper** with hiss-fuse, white flash, swell and a real
  block-destroying **explosion**.
- **World presentation**: drifting blocky **clouds**, distance **fog** matched to the sky colour,
  flat billboarded square **sun & moon**, day/night tinting, water side faces on river banks,
  birch trees mixed into forests, and block-break debris particles.
- **Progression**: experience points from mining ores and defeating mobs, Minecraft-style level
  curve, level-up chime, and the score shown on the death screen.

---

## 7. Save Location

All world saves and persistent user settings are stored locally in the `saves/` directory at the project root:

- **World Saves**: `saves/<world_name>.json` (with automatic `.json.bak` recovery backup)
  - Stores world name, deterministic seed, difficulty, world time & day count, player position/orientation,
    health, hunger, experience, 36-slot inventory, hotbar selection, broken & placed blocks, chests,
    and furnace state.
- **Game Settings**: `saves/settings.json`
  - Stores mouse sensitivity, FOV, render distance, master volume, music toggle, SFX toggle,
    graphics quality, fullscreen mode, and keep-inventory preference.

---

## 8. Project Structure

```text
minecraft_python_game/
│
├── main.py                  # Game entry point, main loop, and input bindings
├── requirements.txt         # Python package dependencies
├── README.md                # Setup, controls, and architecture guide
│
├── game/
│   ├── __init__.py          # Package metadata
│   ├── assets_gen.py        # Procedural pixel-art atlas, GUI sheet, icons, WAV sounds, OBJ models
│   ├── blocks.py            # Block & Item definitions, hardness, tool tiers, UVs
│   ├── terrain.py           # Seeded multi-octave noise terrain, biomes, caves, oak & birch trees, ores
│   ├── chunk.py             # 16x64x16 chunk storage & hidden-face culled mesh builder (+ water sides)
│   ├── world.py             # Chunk streaming, DDA raycast, day/night sky, clouds, fog, explosions
│   ├── player.py            # First-person controller, AABB collision, viewmodel, cracks, XP, survival
│   ├── inventory.py         # 36-slot inventory (9 hotbar + 27 backpack), stacking, durability
│   ├── crafting.py          # Recipes + Minecraft-style shapeless crafting-grid matching
│   ├── furnace.py           # Ore smelting & food cooking system (input, fuel, output, progress)
│   ├── combat.py            # Melee combat, weapon damage, cooldowns, ray hit detection, knockback
│   ├── mobs.py              # Textured animated mobs: Pig, Cow, Sheep, Zombie, Skeleton, Creeper
│   ├── save.py              # Atomic JSON world saving, loading, listing, deletion, and recovery
│   ├── settings.py          # Persistent game settings manager
│   └── ui.py                # MC-style HUD, menus, inventory/crafting/furnace screens, death UI
│
├── assets/
│   ├── textures/            # atlas.png, gui.png widget sheet, container.png, icons/
│   ├── sounds/              # Procedurally synthesized WAV sound effects
│   └── models/              # Wavefront OBJ voxel meshes
│
└── saves/                   # Persistent world saves (*.json) and settings.json
```
