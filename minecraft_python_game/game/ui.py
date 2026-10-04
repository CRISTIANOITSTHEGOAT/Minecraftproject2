"""
Complete Minecraft-style UI & HUD Manager for PyCraft:
- In-game HUD: textured hotbar + selection highlight, heart & hunger icon rows,
  green experience bar with level number, crosshair, item-name popup, F3-style
  debug text, hurt/underwater overlays.
- Inventory / Crafting Table / Furnace screens built from the classic gray
  beveled container window with sunken slots, cursor stack, tooltips,
  durability bars, 2x2 / 3x3 crafting grid + recipe book, furnace flame/arrow.
- Main Menu, New World, Load World, Settings, Pause and Death screens styled
  with the Minecraft dirt backdrop and beveled buttons.
"""

import math
import random
import time as _time
from typing import Callable, Dict, List, Optional

from game.assets_gen import (
    get_container_texture,
    get_gui_texture,
    get_item_icon_texture,
    play_game_sound,
)
from game.blocks import get_block_by_id, get_item_def
from game.furnace import SMELT_RECIPES
from game.inventory import HOTBAR_SIZE, TOTAL_SLOTS, ItemStack

# UI units per Minecraft GUI pixel (gui-scale 2 at 720p: 1 gui px = 2 screen px = 2/720 ui)
GUI_PX = 1.0 / 360.0
WIN_W, WIN_H = 176, 166
HOTBAR_Y = -0.4694
XP_Y = -0.4292
ROW_Y = -0.4125

_GUI_TILE_CACHE: Dict[str, object] = {}


def _tile_texture(tile_name: str):
    """Cached Ursina texture of a single 16x16 atlas tile (for tiled backgrounds)."""
    if tile_name in _GUI_TILE_CACHE:
        return _GUI_TILE_CACHE[tile_name]
    from PIL import Image
    from game.assets_gen import TEXTURES_DIR, _generate_tile_image
    from game.blocks import TILE_COORDS
    from ursina import Texture
    path = TEXTURES_DIR / "atlas.png"
    try:
        col, row = TILE_COORDS[tile_name]
        if path.exists():
            atlas = Image.open(path).convert("RGBA")
            img = atlas.crop((col * 16, row * 16, col * 16 + 16, row * 16 + 16))
        else:
            img = _generate_tile_image(tile_name)
    except Exception:
        img = _generate_tile_image(tile_name)
    tex = Texture(img)
    tex.filtering = "nearest"
    try:
        tex.setWrapU(tex.WM_repeat)
        tex.setWrapV(tex.WM_repeat)
    except Exception:
        pass
    _GUI_TILE_CACHE[tile_name] = tex
    return tex


class ShadowText:
    """Minecraft-style text with an offset black shadow twin."""

    def __init__(self, parent, text, position, scale=1.0, color=None, origin=(0, 0), z=0.0):
        from ursina import Text, color as ucolor
        col = color if color is not None else ucolor.white
        ox, oy = 0.0042 * (scale if scale > 0.4 else 0.6), -0.0042 * (scale if scale > 0.4 else 0.6)
        self._shadow = Text(parent=parent, text=text, origin=origin,
                            position=(position[0] + ox, position[1] + oy), scale=scale,
                            color=ucolor.rgba(0.12, 0.12, 0.12, 0.9), z=z + 0.01)
        self._main = Text(parent=parent, text=text, origin=origin, position=position, scale=scale, color=col, z=z)

    @property
    def text(self):
        return self._main.text

    @text.setter
    def text(self, value):
        self._main.text = value
        self._shadow.text = value

    @property
    def enabled(self):
        return self._main.enabled

    @enabled.setter
    def enabled(self, value):
        self._main.enabled = value
        self._shadow.enabled = value

    @property
    def color(self):
        return self._main.color

    @color.setter
    def color(self, value):
        self._main.color = value

    @property
    def scale(self):
        return self._main.scale

    @scale.setter
    def scale(self, value):
        self._main.scale = value
        self._shadow.scale = value

    @property
    def position(self):
        return self._main.position

    @position.setter
    def position(self, value):
        self._main.position = value
        self._shadow.position = (value[0] + 0.0042, value[1] - 0.0042)

    def destroy(self):
        try:
            from ursina import destroy
            destroy(self._main)
            destroy(self._shadow)
        except Exception:
            pass


class GameUI:
    """Manages all Ursina UI screens, menus, modals, and the in-game HUD."""

    def __init__(self, controller):
        self.ctrl = controller
        self.active_screen: str = "main_menu"
        self.previous_screen: str = "main_menu"
        self.inv_tab: str = "crafting"
        self.inv_table: bool = False
        self.recipe_page: int = 0
        self.book_open: bool = False

        self.new_world_name: str = "Survival World"
        self.new_world_seed: str = "PyCraft2026"
        self.new_world_difficulty: str = "Normal"
        self._world_name_presets = ["Survival World", "Explorer World", "Mountain Realm", "Cavern Frontier", "Island Odyssey"]
        self._name_preset_idx = 0

        # crafting grid (9 slots; first 4 used when no table)
        self.craft_grid: List[Optional[ItemStack]] = [None] * 9

        self.hud_root = None
        self.screen_root = None

        # HUD refs
        self.crosshair = None
        self.hotbar_quad = None
        self.select_quad = None
        self.hotbar_icons: List[object] = []
        self.hotbar_counts: List[ShadowText] = []
        self.hotbar_dur: List[object] = []
        self.hearts: List[object] = []
        self.hungers: List[object] = []
        self.xp_fg = None
        self.level_text: Optional[ShadowText] = None
        self.popup_text: Optional[ShadowText] = None
        self.info_text: Optional[ShadowText] = None
        self.status_banner: Optional[ShadowText] = None
        self.status_timer: float = 0.0
        self.popup_timer: float = 0.0
        self.underwater_overlay = None
        self.hurt_overlay = None
        self._last_selected_slot = -1
        self._splash = None
        self._cursor_icon = None
        self._cursor_count = None
        self._tooltip: Optional[ShadowText] = None
        self._tooltip_bg = None
        self._furnace_flame = None
        self._furnace_arrow = None
        self._inv_slot_widgets: List[dict] = []

        self._init_hud()
        self.show_main_menu()

    # ------------------------------------------------------------------ utils
    def _clear_screen_root(self) -> None:
        try:
            from ursina import Entity, camera, destroy
            if self.screen_root is not None:
                destroy(self.screen_root)
            self.screen_root = Entity(parent=camera.ui)
        except Exception:
            pass

    def set_mouse_locked(self, locked: bool) -> None:
        try:
            from ursina import mouse
            mouse.locked = bool(locked)
            mouse.visible = not bool(locked)
        except Exception:
            pass

    def show_notification(self, message: str, duration: float = 2.5) -> None:
        self.status_timer = duration
        if self.status_banner is not None:
            self.status_banner.text = str(message)
            self.status_banner.enabled = True

    def _win(self, gx: float, gy: float, wx: float = 0.0, wy: float = 0.0):
        """Window-local GUI pixel coords (top-left origin) -> camera.ui coords."""
        return ((gx - WIN_W / 2.0) * GUI_PX + wx, (WIN_H / 2.0 - gy) * GUI_PX + wy)

    def _mc_button(self, parent, label, position, scale, action, text_scale=1.0):
        from ursina import Button, color
        b = Button(
            parent=parent,
            text=label,
            model="quad",
            texture=get_gui_texture("button"),
            position=position,
            scale=scale,
            color=color.rgb(0.78, 0.78, 0.78),
        )
        b.highlight_color = color.white
        b.text_color = color.white
        try:
            b.text_entity.scale = text_scale
        except Exception:
            pass
        b.on_click = action
        return b

    # -------------------------------------------------------------------- HUD
    def _init_hud(self) -> None:
        try:
            from ursina import Entity, camera, color

            self.hud_root = Entity(parent=camera.ui, enabled=False)

            self.underwater_overlay = Entity(parent=self.hud_root, model="quad", scale=(2.2, 1.3), z=0.5,
                                             color=color.rgba(0.08, 0.35, 0.78, 0.42), enabled=False)
            self.hurt_overlay = Entity(parent=self.hud_root, model="quad", scale=(2.2, 1.3), z=0.45,
                                       color=color.rgba(0.85, 0.10, 0.10, 0.35), enabled=False)

            self.crosshair = Entity(parent=self.hud_root, model="quad", texture=get_gui_texture("crosshair"),
                                    scale=(15 * GUI_PX * 1.6, 15 * GUI_PX * 1.6), color=color.white, z=-0.1)

            # Hotbar
            self.hotbar_quad = Entity(parent=self.hud_root, model="quad", texture=get_gui_texture("hotbar"),
                                      scale=(182 * GUI_PX, 22 * GUI_PX), position=(0, HOTBAR_Y), color=color.white, z=0.05)
            self.select_quad = Entity(parent=self.hud_root, model="quad", texture=get_gui_texture("select"),
                                      scale=(24 * GUI_PX, 24 * GUI_PX), position=(0, HOTBAR_Y), color=color.white, z=-0.02)

            for i in range(HOTBAR_SIZE):
                cx = (-80 + 20 * i) * GUI_PX
                icon = Entity(parent=self.hud_root, model="quad", scale=(16 * GUI_PX, 16 * GUI_PX),
                              position=(cx, HOTBAR_Y), color=color.white, enabled=False, z=-0.05)
                cnt = ShadowText(self.hud_root, "", (cx + 8 * GUI_PX, HOTBAR_Y - 8 * GUI_PX), scale=0.62,
                                 origin=(0.5, -0.5), z=-0.06)
                dur_bg = Entity(parent=self.hud_root, model="quad", scale=(13 * GUI_PX, 1.6 * GUI_PX),
                                position=(cx - 1.5 * GUI_PX, HOTBAR_Y - 8.5 * GUI_PX), origin=(-0.5, 0),
                                color=color.rgba(0, 0, 0, 0.8), enabled=False, z=-0.06)
                dur_fg = Entity(parent=self.hud_root, model="quad", scale=(13 * GUI_PX, 1.6 * GUI_PX),
                                position=(cx - 1.5 * GUI_PX, HOTBAR_Y - 8.5 * GUI_PX), origin=(-0.5, 0),
                                color=color.rgb(0.2, 0.9, 0.2), enabled=False, z=-0.07)
                self.hotbar_icons.append(icon)
                self.hotbar_counts.append(cnt)
                self.hotbar_dur.append((dur_bg, dur_fg))

            # Hearts & hunger rows
            for i in range(10):
                hx = (-85.5 + 8 * i) * GUI_PX
                hx2 = (85.5 - 8 * i) * GUI_PX
                h = Entity(parent=self.hud_root, model="quad", texture=get_gui_texture("heart_full"),
                           scale=(9 * GUI_PX, 9 * GUI_PX), position=(hx, ROW_Y), color=color.white, z=0.02)
                g = Entity(parent=self.hud_root, model="quad", texture=get_gui_texture("hunger_full"),
                           scale=(9 * GUI_PX, 9 * GUI_PX), position=(hx2, ROW_Y), color=color.white, z=0.02)
                self.hearts.append(h)
                self.hungers.append(g)

            # XP bar + level
            Entity(parent=self.hud_root, model="quad", texture=get_gui_texture("xp_empty"),
                   scale=(182 * GUI_PX, 5 * GUI_PX), position=(0, XP_Y), color=color.white, z=0.02)
            self.xp_fg = Entity(parent=self.hud_root, model="quad", texture=get_gui_texture("xp_full"),
                                scale=(0.0, 5 * GUI_PX), position=(-91 * GUI_PX, XP_Y), origin=(-0.5, 0),
                                color=color.white, z=0.0)
            self.level_text = ShadowText(self.hud_root, "", (0, ROW_Y + 0.012), scale=0.85,
                                         color=color.rgb(0.5, 1.0, 0.2), origin=(0, 0), z=-0.02)
            self.level_text.enabled = False

            # Held item name popup
            self.popup_text = ShadowText(self.hud_root, "", (0, -0.365), scale=1.0,
                                         color=color.rgb(1.0, 1.0, 1.0), origin=(0, 0), z=-0.1)
            self.popup_text.enabled = False

            # Debug / world info (F3 style)
            self.info_text = ShadowText(self.hud_root, "", (-0.865, 0.47), scale=0.62,
                                        color=color.rgb(0.92, 0.95, 1.0), origin=(-0.5, 0.5), z=-0.1)

            self.status_banner = ShadowText(self.hud_root, "", (0, 0.34), scale=1.0,
                                            color=color.rgb(1.0, 0.92, 0.38), origin=(0, 0), z=-0.2)
            self.status_banner.enabled = False
        except Exception as exc:
            print(f"[UI] Warning initializing HUD: {exc}")

    def update_hud(self, dt: float) -> None:
        if self.hud_root is None:
            return
        player = self.ctrl.player
        world = self.ctrl.world
        if player is None or world is None:
            return
        try:
            from ursina import color, time as utime

            if self.status_timer > 0.0:
                self.status_timer -= dt
                if self.status_timer <= 0.0 and self.status_banner is not None:
                    self.status_banner.enabled = False
            if self.popup_timer > 0.0:
                self.popup_timer -= dt
                if self.popup_timer <= 0.0 and self.popup_text is not None:
                    self.popup_text.enabled = False

            if self.underwater_overlay is not None:
                self.underwater_overlay.enabled = bool(player.head_underwater)
            if self.hurt_overlay is not None:
                self.hurt_overlay.enabled = player.hurt_flash_timer > 0.0

            # Hotbar selection highlight + item name popup on change
            sel = player.inventory.selected_slot
            if sel != self._last_selected_slot:
                self._last_selected_slot = sel
                if self.select_quad is not None:
                    self.select_quad.position = ((-80 + 20 * sel) * GUI_PX, HOTBAR_Y)
                st = player.inventory.slots[sel]
                if self.popup_text is not None:
                    if st is not None and st.item_def is not None:
                        self.popup_text.text = st.item_def.name
                        self.popup_text.enabled = True
                        self.popup_timer = 2.0
                    else:
                        self.popup_text.enabled = False
                        self.popup_timer = 0.0

            # Hotbar contents
            for i in range(HOTBAR_SIZE):
                st = player.inventory.slots[i]
                icon = self.hotbar_icons[i]
                cnt = self.hotbar_counts[i]
                dur_bg, dur_fg = self.hotbar_dur[i]
                if st is not None:
                    icon.texture = get_item_icon_texture(st.item_id)
                    icon.enabled = True
                    cnt.text = str(st.count) if st.count > 1 else ""
                    if st.durability is not None and st.max_durability:
                        frac = max(0.0, min(1.0, st.durability / st.max_durability))
                        dur_bg.enabled = True
                        dur_fg.enabled = True
                        dur_fg.scale_x = 13 * GUI_PX * frac
                        if frac > 0.5:
                            dur_fg.color = color.rgb(0.2, 0.9, 0.2)
                        elif frac > 0.25:
                            dur_fg.color = color.rgb(0.95, 0.75, 0.1)
                        else:
                            dur_fg.color = color.rgb(0.9, 0.2, 0.15)
                    else:
                        dur_bg.enabled = False
                        dur_fg.enabled = False
                else:
                    icon.enabled = False
                    cnt.text = ""
                    dur_bg.enabled = False
                    dur_fg.enabled = False

            # Hearts
            hp = player.health
            for i in range(10):
                val = max(0.0, min(2.0, hp - 2.0 * i))
                tex_name = "heart_full" if val >= 2 else ("heart_half" if val >= 1 else "heart_empty")
                self.hearts[i].texture = get_gui_texture(tex_name)
            hg = player.hunger
            for i in range(10):
                val = max(0.0, min(2.0, hg - 2.0 * i))
                tex_name = "hunger_full" if val >= 2 else ("hunger_half" if val >= 1 else "hunger_empty")
                self.hungers[i].texture = get_gui_texture(tex_name)

            # XP bar + level number
            if self.xp_fg is not None:
                self.xp_fg.scale_x = (182 * GUI_PX) * max(0.0, min(1.0, player.xp_progress))
            if self.level_text is not None:
                if player.xp_level > 0:
                    self.level_text.text = str(player.xp_level)
                    self.level_text.enabled = True
                else:
                    self.level_text.enabled = False

            # Debug info
            if self.info_text is not None:
                fps = int(round(1.0 / max(0.001, getattr(utime, "dt", 0.016))))
                px, py, pz = player.position
                biome, _ = world.terrain.get_biome_and_height(int(px), int(pz))
                self.info_text.text = (
                    f"XYZ: {px:.1f} / {py:.1f} / {pz:.1f}   FPS: {min(240, fps)}\n"
                    f"Seed: {world.seed}   Biome: {biome}\n"
                    f"{world.get_time_label()}   {world.difficulty}"
                )
        except Exception:
            pass

    def update_frame(self, dt: float) -> None:
        """Per-frame updates that run on every screen (cursor stack, tooltip, furnace anims)."""
        try:
            from ursina import mouse
            # main-menu splash pulse
            if self._splash is not None and self.active_screen == "main_menu":
                self._splash.scale = 0.85 + 0.06 * abs(math.sin(_time.time() * 4.0))
            if self.active_screen != "inventory":
                return
            inv = self.ctrl.player.inventory if self.ctrl.player else None
            if inv is None:
                return
            # cursor stack follows the mouse
            if self._cursor_icon is not None:
                if inv.cursor_stack is not None:
                    self._cursor_icon.texture = get_item_icon_texture(inv.cursor_stack.item_id)
                    self._cursor_icon.enabled = True
                    self._cursor_icon.position = (mouse.position[0] + 0.012, mouse.position[1] - 0.012)
                    if self._cursor_count is not None:
                        self._cursor_count.text = str(inv.cursor_stack.count) if inv.cursor_stack.count > 1 else ""
                        self._cursor_count.position = (mouse.position[0] + 0.030, mouse.position[1] - 0.034)
                else:
                    self._cursor_icon.enabled = False
                    if self._cursor_count is not None:
                        self._cursor_count.text = ""
            # tooltip for hovered slot
            tip = self._hovered_tooltip()
            if self._tooltip is not None:
                if tip:
                    self._tooltip.text = tip
                    self._tooltip.enabled = True
                    self._tooltip.position = (mouse.position[0] + 0.02, mouse.position[1] - 0.05)
                    if self._tooltip_bg is not None:
                        w = len(tip) * 0.0092 + 0.02
                        self._tooltip_bg.enabled = True
                        self._tooltip_bg.scale = (w, 0.042)
                        self._tooltip_bg.position = (mouse.position[0] + 0.018 + w / 2 - 0.008, mouse.position[1] - 0.048)
                else:
                    self._tooltip.enabled = False
                    if self._tooltip_bg is not None:
                        self._tooltip_bg.enabled = False
            # furnace progress animation
            if self.inv_tab == "furnace" and self._furnace_flame is not None:
                furn = self.ctrl.furnace
                fp = max(0.0, min(1.0, furn.fuel_progress))
                pr = max(0.0, min(1.0, furn.progress))
                self._furnace_flame.scale_y = 14 * GUI_PX * fp
                self._furnace_flame.texture_scale = (1, max(0.001, fp))
                self._furnace_arrow.scale_x = 22 * GUI_PX * pr
                self._furnace_arrow.texture_scale = (max(0.001, pr), 1)
        except Exception:
            pass

    def _hovered_tooltip(self) -> str:
        try:
            from ursina import mouse
            ent = mouse.hovered_entity
            if ent is None:
                return ""
            key = getattr(ent, "tooltip_key", None)
            if not key:
                return ""
            item_key, extra = key
            idef = get_item_def(item_key)
            if idef is None:
                return ""
            txt = idef.name
            if extra:
                txt += f" ({extra})"
            return txt
        except Exception:
            return ""

    # ---------------------------------------------------------------- screens
    def show_hud_only(self) -> None:
        if self.ctrl.player is not None:
            self._return_grid_to_inventory()
            self.ctrl.player.inventory.return_cursor_to_inventory()
        self._clear_screen_root()
        self.active_screen = "hud"
        if self.hud_root is not None:
            self.hud_root.enabled = True
        self.set_mouse_locked(True)

    def _return_grid_to_inventory(self) -> None:
        if self.ctrl.player is None:
            self.craft_grid = [None] * 9
            return
        for i, st in enumerate(self.craft_grid):
            if st is not None:
                self.ctrl.player.inventory.add_item(st.item_id, st.count, st.durability)
                self.craft_grid[i] = None

    # ------------------------------------------------------------- main menu
    def _dirt_backdrop(self, darkness=0.32):
        from ursina import Entity, color
        bg = Entity(parent=self.screen_root, model="quad", scale=(2.4, 1.4), z=0.2,
                    texture=_tile_texture("dirt"), color=color.rgb(darkness, darkness * 0.96, darkness * 0.92))
        try:
            bg.texture_scale = (14, 8)
        except Exception:
            pass
        return bg

    def show_main_menu(self) -> None:
        self._clear_screen_root()
        self.active_screen = "main_menu"
        if self.hud_root is not None:
            self.hud_root.enabled = False
        self.set_mouse_locked(False)
        try:
            from ursina import Entity, Text, color

            self._dirt_backdrop()

            logo = ShadowText(self.screen_root, "PyCraft", (0, 0.30), scale=3.2,
                              color=color.rgb(1.0, 0.94, 0.42), origin=(0, 0), z=-0.05)
            ShadowText(self.screen_root, "VOXEL SURVIVAL SANDBOX", (0, 0.215), scale=1.0,
                       color=color.rgb(0.85, 0.88, 0.95), origin=(0, 0), z=-0.05)
            self._splash = Text(parent=self.screen_root, text="Now with Creepers!", origin=(0, 0),
                                position=(0.30, 0.335), scale=0.85, color=color.rgb(1.0, 0.9, 0.2),
                                rotation_z=-16, z=-0.06)

            btn_specs = [
                ("Singleplayer  (New World)", 0.06, self.show_new_world_menu),
                ("Load World", -0.03, self.show_load_world_menu),
                ("Settings", -0.12, lambda: self.show_settings_menu(return_to="main_menu")),
                ("Quit Game", -0.21, self.ctrl.quit_application),
            ]
            for label, ypos, action in btn_specs:
                self._mc_button(self.screen_root, label, (0, ypos), (0.42, 0.062), action, text_scale=0.9)

            Text(parent=self.screen_root, text="PyCraft Rework 1.0", origin=(-0.5, -0.5), position=(-0.875, -0.47),
                 scale=0.6, color=color.rgb(0.75, 0.75, 0.75), z=-0.05)
            Text(parent=self.screen_root, text="Not an official Minecraft product", origin=(0.5, -0.5),
                 position=(0.875, -0.47), scale=0.6, color=color.rgb(0.75, 0.75, 0.75), z=-0.05)
            del logo
        except Exception as exc:
            print(f"[UI] Error building main menu: {exc}")

    def show_new_world_menu(self) -> None:
        self._clear_screen_root()
        self.active_screen = "new_world"
        self.set_mouse_locked(False)
        try:
            from ursina import Button, Entity, InputField, color

            self._dirt_backdrop(0.22)
            Entity(parent=self.screen_root, model="quad", texture=get_container_texture(),
                   scale=(WIN_W * GUI_PX * 1.5, WIN_H * GUI_PX * 1.32), position=(0, 0), color=color.white, z=0.1)

            ShadowText(self.screen_root, "Create New World", (0, 0.27), scale=1.5,
                       color=color.rgb(0.25, 0.25, 0.25), origin=(0, 0), z=-0.05)

            ShadowText(self.screen_root, "World Name:", (-0.34, 0.15), scale=0.9, color=color.rgb(0.2, 0.2, 0.2), origin=(-0.5, 0), z=-0.05)
            name_input = InputField(parent=self.screen_root, default_value=self.new_world_name,
                                    position=(0.05, 0.15), scale=(0.42, 0.05), color=color.rgb(0.15, 0.15, 0.17))

            def cycle_name():
                self._name_preset_idx = (self._name_preset_idx + 1) % len(self._world_name_presets)
                self.new_world_name = self._world_name_presets[self._name_preset_idx]
                name_input.text = self.new_world_name

            self._mc_button(self.screen_root, "Preset", (0.34, 0.15), (0.13, 0.05), cycle_name, text_scale=0.8)

            ShadowText(self.screen_root, "World Seed:", (-0.34, 0.06), scale=0.9, color=color.rgb(0.2, 0.2, 0.2), origin=(-0.5, 0), z=-0.05)
            seed_input = InputField(parent=self.screen_root, default_value=self.new_world_seed,
                                    position=(0.05, 0.06), scale=(0.42, 0.05), color=color.rgb(0.15, 0.15, 0.17))

            def randomize_seed():
                self.new_world_seed = f"Seed{random.randint(10000, 99999)}"
                seed_input.text = self.new_world_seed

            self._mc_button(self.screen_root, "Random", (0.34, 0.06), (0.13, 0.05), randomize_seed, text_scale=0.8)

            ShadowText(self.screen_root, "Difficulty:", (-0.34, -0.04), scale=0.9, color=color.rgb(0.2, 0.2, 0.2), origin=(-0.5, 0), z=-0.05)
            diffs = ["Peaceful", "Easy", "Normal", "Hard"]
            diff_buttons: List[Button] = []

            def select_diff(d_val: str):
                self.new_world_difficulty = d_val
                for btn in diff_buttons:
                    btn.color = color.rgb(0.55, 0.75, 0.55) if btn.text == d_val else color.rgb(0.78, 0.78, 0.78)

            for idx, d_name in enumerate(diffs):
                bx = -0.16 + idx * 0.145
                btn = self._mc_button(self.screen_root, d_name, (bx, -0.04), (0.13, 0.05),
                                      lambda dn=d_name: select_diff(dn), text_scale=0.8)
                if d_name == self.new_world_difficulty:
                    btn.color = color.rgb(0.55, 0.75, 0.55)
                diff_buttons.append(btn)

            def on_create():
                w_name = getattr(name_input, "text", "").strip() or self.new_world_name
                w_seed = getattr(seed_input, "text", "").strip() or self.new_world_seed
                self.ctrl.start_new_world(world_name=w_name, seed=w_seed, difficulty=self.new_world_difficulty)

            self._mc_button(self.screen_root, "Create New World", (-0.11, -0.18), (0.34, 0.062), on_create, text_scale=0.9)
            self._mc_button(self.screen_root, "Cancel", (0.24, -0.18), (0.18, 0.062), self.show_main_menu, text_scale=0.9)
        except Exception as exc:
            print(f"[UI] Error building new world menu: {exc}")

    def show_load_world_menu(self) -> None:
        self._clear_screen_root()
        self.active_screen = "load_world"
        self.set_mouse_locked(False)
        try:
            from ursina import Entity, color

            self._dirt_backdrop(0.22)
            Entity(parent=self.screen_root, model="quad", texture=get_container_texture(),
                   scale=(WIN_W * GUI_PX * 1.7, WIN_H * GUI_PX * 1.4), position=(0, 0), color=color.white, z=0.1)
            ShadowText(self.screen_root, "Select World", (0, 0.31), scale=1.5,
                       color=color.rgb(0.25, 0.25, 0.25), origin=(0, 0), z=-0.05)

            worlds = self.ctrl.save_manager.list_saved_worlds()
            if not worlds:
                ShadowText(self.screen_root, "No saved worlds yet - create one!", (0, 0.05), scale=1.0,
                           color=color.rgb(0.3, 0.3, 0.3), origin=(0, 0), z=-0.05)
            else:
                for idx, winfo in enumerate(worlds[:5]):
                    ypos = 0.20 - idx * 0.085
                    slug = winfo["slug"]
                    label = f"{winfo['world_name']}  -  {winfo['seed']}  -  {winfo['difficulty']} (Day {winfo['day_count']})"
                    ShadowText(self.screen_root, label, (-0.40, ypos), scale=0.8,
                               color=color.rgb(0.2, 0.2, 0.2), origin=(-0.5, 0), z=-0.05)
                    self._mc_button(self.screen_root, "Play", (0.30, ypos), (0.11, 0.055),
                                    lambda s=slug: self.ctrl.load_saved_world(s), text_scale=0.8)
                    self._mc_button(self.screen_root, "Delete", (0.43, ypos), (0.11, 0.055),
                                    lambda s=slug: (self.ctrl.save_manager.delete_world(s), self.show_load_world_menu()), text_scale=0.8)

            self._mc_button(self.screen_root, "Back", (0, -0.30), (0.24, 0.06), self.show_main_menu, text_scale=0.9)
        except Exception as exc:
            print(f"[UI] Error building load world menu: {exc}")

    def show_settings_menu(self, return_to: str = "main_menu") -> None:
        self._clear_screen_root()
        self.previous_screen = return_to
        self.active_screen = "settings"
        if self.hud_root is not None:
            self.hud_root.enabled = False
        self.set_mouse_locked(False)
        s = self.ctrl.settings
        try:
            from ursina import Entity, color

            self._dirt_backdrop(0.18)
            Entity(parent=self.screen_root, model="quad", texture=get_container_texture(),
                   scale=(WIN_W * GUI_PX * 1.6, WIN_H * GUI_PX * 1.4), position=(0, 0), color=color.white, z=0.1)
            ShadowText(self.screen_root, "Settings", (0, 0.32), scale=1.5,
                       color=color.rgb(0.25, 0.25, 0.25), origin=(0, 0), z=-0.05)

            def refresh():
                s.save()
                s.apply_to_engine()
                self.show_settings_menu(return_to=return_to)

            rows = [
                (f"Mouse Sensitivity: {int(s.mouse_sensitivity)}",
                 lambda: (setattr(s, "mouse_sensitivity", max(10, s.mouse_sensitivity - 5)), refresh()),
                 lambda: (setattr(s, "mouse_sensitivity", min(150, s.mouse_sensitivity + 5)), refresh())),
                (f"FOV: {int(s.fov)}",
                 lambda: (setattr(s, "fov", max(60, s.fov - 5)), refresh()),
                 lambda: (setattr(s, "fov", min(120, s.fov + 5)), refresh())),
                (f"Render Distance: {int(s.render_distance)} chunks",
                 lambda: (setattr(s, "render_distance", max(2, s.render_distance - 1)), refresh()),
                 lambda: (setattr(s, "render_distance", min(6, s.render_distance + 1)), refresh())),
                (f"Volume: {int(round(s.volume * 100))}%",
                 lambda: (setattr(s, "volume", max(0.0, round(s.volume - 0.1, 2))), refresh()),
                 lambda: (setattr(s, "volume", min(1.0, round(s.volume + 0.1, 2))), refresh())),
            ]
            for idx, (label, dec_fn, inc_fn) in enumerate(rows):
                ypos = 0.20 - idx * 0.075
                ShadowText(self.screen_root, label, (-0.36, ypos), scale=0.85, color=color.rgb(0.2, 0.2, 0.2), origin=(-0.5, 0), z=-0.05)
                self._mc_button(self.screen_root, "-", (0.22, ypos), (0.07, 0.05), dec_fn, text_scale=0.9)
                self._mc_button(self.screen_root, "+", (0.32, ypos), (0.07, 0.05), inc_fn, text_scale=0.9)

            toggles = [
                (f"Music: {'ON' if s.music else 'OFF'}", (-0.24, -0.12), lambda: (setattr(s, "music", not s.music), refresh())),
                (f"Sound: {'ON' if s.sound_effects else 'OFF'}", (0.04, -0.12), lambda: (setattr(s, "sound_effects", not s.sound_effects), refresh())),
                (f"Fullscreen: {'ON' if s.fullscreen else 'OFF'}", (0.32, -0.12), lambda: (setattr(s, "fullscreen", not s.fullscreen), refresh())),
                (f"Graphics: {s.graphics_quality}", (-0.14, -0.20),
                 lambda: (setattr(s, "graphics_quality", {"Low": "Medium", "Medium": "High", "High": "Low"}.get(s.graphics_quality, "High")), refresh())),
                (f"Keep Inventory: {'ON' if s.keep_inventory else 'OFF'}", (0.22, -0.20), lambda: (setattr(s, "keep_inventory", not s.keep_inventory), refresh())),
            ]
            for t_label, t_pos, t_fn in toggles:
                self._mc_button(self.screen_root, t_label, t_pos, (0.26, 0.055), t_fn, text_scale=0.75)

            def go_back():
                s.save()
                s.apply_to_engine()
                if return_to == "pause":
                    self.show_pause_menu()
                else:
                    self.show_main_menu()

            self._mc_button(self.screen_root, "Done", (0, -0.31), (0.26, 0.06), go_back, text_scale=0.9)
        except Exception as exc:
            print(f"[UI] Error building settings menu: {exc}")

    def show_pause_menu(self) -> None:
        self._clear_screen_root()
        self.active_screen = "pause"
        if self.hud_root is not None:
            self.hud_root.enabled = False
        self.set_mouse_locked(False)
        try:
            from ursina import Entity, color

            Entity(parent=self.screen_root, model="quad", scale=(2.4, 1.4), color=color.rgba(0.02, 0.03, 0.05, 0.62), z=0.2)
            ShadowText(self.screen_root, "Game Menu", (0, 0.24), scale=1.6, color=color.white, origin=(0, 0), z=-0.05)

            def on_save():
                if self.ctrl.save_current_world():
                    self.show_hud_only()
                    self.show_notification("World saved!")

            def on_save_quit():
                self.ctrl.save_current_world()
                self.ctrl.return_to_main_menu()

            btns = [
                ("Back to Game", 0.10, self.show_hud_only),
                ("Save World", 0.01, on_save),
                ("Options...", -0.08, lambda: self.show_settings_menu(return_to="pause")),
                ("Save and Quit to Title", -0.17, on_save_quit),
            ]
            for lbl, yp, fn in btns:
                self._mc_button(self.screen_root, lbl, (0, yp), (0.40, 0.062), fn, text_scale=0.9)
        except Exception as exc:
            print(f"[UI] Error building pause menu: {exc}")

    def show_death_screen(self) -> None:
        self._clear_screen_root()
        self.active_screen = "death"
        if self.hud_root is not None:
            self.hud_root.enabled = False
        self.set_mouse_locked(False)
        reason = getattr(self.ctrl.player, "death_reason", "") or "You lost all health"
        try:
            from ursina import Entity, color
            Entity(parent=self.screen_root, model="quad", scale=(2.4, 1.4), color=color.rgba(0.42, 0.03, 0.03, 0.72), z=0.2)
            ShadowText(self.screen_root, "You Died!", (0, 0.16), scale=2.6, color=color.rgb(1.0, 0.28, 0.28), origin=(0, 0), z=-0.05)
            ShadowText(self.screen_root, reason, (0, 0.05), scale=1.0, color=color.rgb(0.95, 0.85, 0.85), origin=(0, 0), z=-0.05)
            score = getattr(self.ctrl.player, "xp_level", 0)
            ShadowText(self.screen_root, f"Score:  {score} levels of experience", (0, -0.02), scale=0.9,
                       color=color.rgb(0.9, 0.9, 0.75), origin=(0, 0), z=-0.05)
            self._mc_button(self.screen_root, "Respawn", (0, -0.14), (0.36, 0.065), self.ctrl.respawn_player, text_scale=0.95)
            self._mc_button(self.screen_root, "Title Screen", (0, -0.23), (0.36, 0.06), self.ctrl.return_to_main_menu, text_scale=0.95)
        except Exception as exc:
            print(f"[UI] Error building death screen: {exc}")

    # ---------------------------------------------------------- inventory UI
    def show_inventory_screen(self, mode: str = "crafting", table: Optional[bool] = None) -> None:
        self._clear_screen_root()
        self.active_screen = "inventory"
        if mode == "furnace":
            self.inv_tab = "furnace"
        else:
            self.inv_tab = "crafting"
            if table is not None:
                self.inv_table = bool(table)
        if self.hud_root is not None:
            self.hud_root.enabled = False
        self.set_mouse_locked(False)

        player = self.ctrl.player
        if player is None:
            return
        try:
            from ursina import Button, Entity, Text, color

            Entity(parent=self.screen_root, model="quad", scale=(2.4, 1.4), color=color.rgba(0.05, 0.05, 0.08, 0.55), z=0.25)
            wy = 0.02
            Entity(parent=self.screen_root, model="quad", texture=get_container_texture(),
                   scale=(WIN_W * GUI_PX, WIN_H * GUI_PX), position=(0, wy), color=color.white, z=0.1)

            self._inv_slot_widgets = []

            if self.inv_tab == "furnace":
                title = "Furnace"
            elif self.inv_table:
                title = "Crafting"
            else:
                title = "Inventory"
            ShadowText(self.screen_root, title, self._win(8, 7, 0, wy), scale=0.85,
                       color=color.rgb(0.25, 0.25, 0.25), origin=(-0.5, 0), z=-0.05)
            ShadowText(self.screen_root, "Inventory", self._win(8, 74 if self.inv_tab != "furnace" else 74, 0, wy),
                       scale=0.85, color=color.rgb(0.25, 0.25, 0.25), origin=(-0.5, 0), z=-0.05)

            # ---- inventory slots: 27 main + 9 hotbar
            for row in range(3):
                for col in range(9):
                    s_idx = 9 + row * 9 + col
                    gx, gy = 8 + col * 18, 84 + row * 18
                    self._make_inv_slot(s_idx, gx, gy, wy)
            for col in range(9):
                self._make_inv_slot(col, 8 + col * 18, 142, wy)

            # ---- mode-specific top area
            if self.inv_tab == "crafting":
                self._build_crafting_area(wy)
            else:
                self._build_furnace_area(wy)

            # ---- tabs / close buttons (small, top-right of window)
            tab_y = wy + WIN_H / 2 * GUI_PX + 0.02
            b_craft = self._mc_button(self.screen_root, "Crafting", (-0.16, tab_y), (0.14, 0.04),
                                      lambda: self.show_inventory_screen("crafting", table=self.inv_table), text_scale=0.7)
            b_furn = self._mc_button(self.screen_root, "Furnace", (-0.01, tab_y), (0.12, 0.04),
                                      lambda: self.show_inventory_screen("furnace"), text_scale=0.7)
            b_book = self._mc_button(self.screen_root, "Recipes", (0.12, tab_y), (0.12, 0.04),
                                      lambda: (setattr(self, "book_open", not self.book_open),
                                               self.show_inventory_screen(self.inv_tab, table=self.inv_table)), text_scale=0.7)
            b_close = self._mc_button(self.screen_root, "X", (0.255, tab_y), (0.035, 0.04),
                                      self.show_hud_only, text_scale=0.7)
            if self.inv_tab == "crafting":
                b_craft.color = color.rgb(0.6, 0.8, 0.6)
            else:
                b_furn.color = color.rgb(0.6, 0.8, 0.6)

            if self.book_open and self.inv_tab == "crafting":
                self._build_recipe_book(wy)

            # ---- cursor stack + tooltip overlays
            self._cursor_icon = Entity(parent=self.screen_root, model="quad", scale=(18 * GUI_PX, 18 * GUI_PX),
                                       color=color.white, enabled=False, z=-0.4)
            self._cursor_count = ShadowText(self.screen_root, "", (0, 0), scale=0.7, origin=(0.5, -0.5), z=-0.45)
            self._tooltip_bg = Entity(parent=self.screen_root, model="quad", scale=(0.2, 0.045),
                                      color=color.rgba(0.06, 0.0, 0.10, 0.88), enabled=False, z=-0.5, origin=(-0.5, 0))
            self._tooltip = ShadowText(self.screen_root, "", (0, 0), scale=0.8, color=color.rgb(1.0, 1.0, 1.0),
                                       origin=(-0.5, 0), z=-0.55)
            self._tooltip.enabled = False
        except Exception as exc:
            print(f"[UI] Error building inventory screen: {exc}")

    # slot factory ------------------------------------------------------
    def _make_slot(self, gx, gy, wy, click_fn, tooltip_key=None):
        from ursina import Button, Entity, color
        pos = self._win(gx + 9, gy + 9, 0, wy)
        btn = Button(parent=self.screen_root, text="", model="quad", texture=get_gui_texture("slot"),
                     position=pos, scale=(18 * GUI_PX, 18 * GUI_PX), color=color.white, z=-0.02)
        btn.highlight_color = color.white
        btn.on_click = click_fn
        if tooltip_key:
            btn.tooltip_key = tooltip_key
        icon = Entity(parent=self.screen_root, model="quad", scale=(16 * GUI_PX, 16 * GUI_PX),
                      position=pos, color=color.white, enabled=False, z=-0.05)
        cnt = ShadowText(self.screen_root, "", (pos[0] + 8 * GUI_PX, pos[1] - 8 * GUI_PX), scale=0.6,
                         origin=(0.5, -0.5), z=-0.06)
        dur = Entity(parent=self.screen_root, model="quad", scale=(0, 1.6 * GUI_PX),
                     position=(pos[0] - 6.5 * GUI_PX, pos[1] - 7.5 * GUI_PX), origin=(-0.5, 0),
                     color=color.rgb(0.2, 0.9, 0.2), enabled=False, z=-0.06)
        widget = {"btn": btn, "icon": icon, "cnt": cnt, "dur": dur}
        self._inv_slot_widgets.append(widget)
        return widget

    def _fill_widget(self, widget, st):
        from ursina import color
        if st is not None:
            widget["icon"].texture = get_item_icon_texture(st.item_id)
            widget["icon"].enabled = True
            widget["cnt"].text = str(st.count) if st.count > 1 else ""
            if st.durability is not None and st.max_durability:
                frac = max(0.0, min(1.0, st.durability / st.max_durability))
                widget["dur"].enabled = True
                widget["dur"].scale_x = 13 * GUI_PX * frac
                widget["dur"].color = color.rgb(0.2, 0.9, 0.2) if frac > 0.5 else (color.rgb(0.95, 0.75, 0.1) if frac > 0.25 else color.rgb(0.9, 0.2, 0.15))
            else:
                widget["dur"].enabled = False
            idef = st.item_def
            extra = f"{st.durability}/{st.max_durability}" if (st.durability is not None and st.max_durability) else None
            widget["btn"].tooltip_key = (st.item_id, extra)
        else:
            widget["icon"].enabled = False
            widget["cnt"].text = ""
            widget["dur"].enabled = False
            widget["btn"].tooltip_key = None

    def _make_inv_slot(self, slot_idx, gx, gy, wy):
        def click(idx=slot_idx):
            from ursina import mouse, held_keys
            right = bool(held_keys["right mouse"])
            self.ctrl.player.inventory.click_slot(idx, right_click=right)
            self.ctrl.player.update_held_visual()
            self.show_inventory_screen(self.inv_tab, table=self.inv_table)
        w = self._make_slot(gx, gy, wy, click)
        self._fill_widget(w, self.ctrl.player.inventory.slots[slot_idx])

    # crafting / furnace areas -------------------------------------------
    def _click_stack_list(self, lst, idx, right):
        inv = self.ctrl.player.inventory
        cur = inv.cursor_stack
        st = lst[idx]
        if not right:
            if cur is None:
                inv.cursor_stack = st
                lst[idx] = None
            elif st is None:
                lst[idx] = cur
                inv.cursor_stack = None
            elif st.item_id == cur.item_id and st.durability is None:
                space = st.max_stack - st.count
                move = min(space, cur.count)
                st.count += move
                cur.count -= move
                inv.cursor_stack = None if cur.count <= 0 else cur
            else:
                lst[idx] = cur
                inv.cursor_stack = st
        else:
            if cur is None and st is not None:
                half = (st.count + 1) // 2
                inv.cursor_stack = ItemStack(st.item_id, half, st.durability)
                st.count -= half
                if st.count <= 0:
                    lst[idx] = None
            elif cur is not None:
                if st is None:
                    lst[idx] = ItemStack(cur.item_id, 1, cur.durability)
                    cur.count -= 1
                    if cur.count <= 0:
                        inv.cursor_stack = None
                elif st.item_id == cur.item_id and st.count < st.max_stack and st.durability is None:
                    st.count += 1
                    cur.count -= 1
                    if cur.count <= 0:
                        inv.cursor_stack = None

    def _build_crafting_area(self, wy):
        from ursina import Button, Entity, color
        inv = self.ctrl.player.inventory
        cs = self.ctrl.crafting
        grid_size = 3 if self.inv_table else 2
        gx0 = 30 if self.inv_table else 44
        gy0 = 17

        for r in range(grid_size):
            for c in range(grid_size):
                gi = r * 3 + c if self.inv_table else r * 2 + c
                gx, gy = gx0 + c * 18, gy0 + r * 18

                def click(i=gi):
                    from ursina import held_keys
                    right = bool(held_keys["right mouse"])
                    self._click_stack_list(self.craft_grid, i, right)
                    self.show_inventory_screen("crafting", table=self.inv_table)

                w = self._make_slot(gx, gy, wy, click)
                self._fill_widget(w, self.craft_grid[gi])

        # result slot
        recipe = cs.match_grid([self.craft_grid[i] for i in range(9 if self.inv_table else 4)],
                               grid_size=grid_size, has_table=self.inv_table)

        def result_click():
            rec = cs.match_grid([self.craft_grid[i] for i in range(9 if self.inv_table else 4)],
                                grid_size=grid_size, has_table=self.inv_table)
            if rec is None:
                return
            cur = inv.cursor_stack
            if cur is not None and (cur.item_id != rec.result_item or cur.count + rec.result_count > cur.max_stack):
                return
            if cur is None:
                inv.cursor_stack = ItemStack(rec.result_item, rec.result_count)
            else:
                cur.count += rec.result_count
            for i in range(9):
                st = self.craft_grid[i]
                if st is not None:
                    st.count -= 1
                    if st.count <= 0:
                        self.craft_grid[i] = None
            play_game_sound("craft", self.ctrl.settings)
            self.ctrl.player.update_held_visual()
            self.show_inventory_screen("crafting", table=self.inv_table)

        rw = self._make_slot(124 if self.inv_table else 108, 35 if self.inv_table else 26, wy, result_click)
        if recipe is not None:
            self._fill_widget(rw, ItemStack(recipe.result_item, recipe.result_count))
            rw["btn"].tooltip_key = (recipe.result_item, None)

    def _build_furnace_area(self, wy):
        from ursina import Entity, color
        furn = self.ctrl.furnace
        inv = self.ctrl.player.inventory

        def input_click():
            from ursina import held_keys
            right = bool(held_keys["right mouse"])
            self._click_furnace_slot("input_slot", right)
            self.show_inventory_screen("furnace")

        def fuel_click():
            from ursina import held_keys
            right = bool(held_keys["right mouse"])
            self._click_furnace_slot("fuel_slot", right)
            self.show_inventory_screen("furnace")

        def out_click():
            from ursina import held_keys
            right = bool(held_keys["right mouse"])
            st = furn.output_slot
            cur = inv.cursor_stack
            if st is not None:
                take = st.count if not right else 1
                if cur is None:
                    inv.cursor_stack = ItemStack(st.item_id, take, st.durability)
                elif cur.item_id == st.item_id and cur.count + take <= cur.max_stack:
                    cur.count += take
                else:
                    return
                st.count -= take
                if st.count <= 0:
                    furn.output_slot = None
                play_game_sound("pop", self.ctrl.settings)
                self.ctrl.player.update_held_visual()
            self.show_inventory_screen("furnace")

        w_in = self._make_slot(56, 17, wy, input_click)
        self._fill_widget(w_in, furn.input_slot)
        w_fuel = self._make_slot(56, 53, wy, fuel_click)
        self._fill_widget(w_fuel, furn.fuel_slot)
        w_out = self._make_slot(116, 35, wy, out_click)
        self._fill_widget(w_out, furn.output_slot)

        # flame + arrow progress sprites (animated in update_frame)
        fp = max(0.0, min(1.0, furn.fuel_progress))
        pr = max(0.0, min(1.0, furn.progress))
        fpos = self._win(56 + 7, 35 + 14, 0, wy)
        Entity(parent=self.screen_root, model="quad", texture=get_gui_texture("flame_empty"),
               scale=(14 * GUI_PX, 14 * GUI_PX), position=self._win(63, 42, 0, wy), color=color.white, z=-0.04)
        self._furnace_flame = Entity(parent=self.screen_root, model="quad", texture=get_gui_texture("flame"),
                                     scale=(14 * GUI_PX, 14 * GUI_PX * fp), position=(fpos[0], fpos[1]),
                                     origin=(0, -0.5), color=color.white, z=-0.05)
        try:
            self._furnace_flame.texture_scale = (1, max(0.001, fp))
        except Exception:
            pass
        apos = self._win(90, 39, 0, wy)
        Entity(parent=self.screen_root, model="quad", texture=get_gui_texture("arrow_empty"),
               scale=(22 * GUI_PX, 9 * GUI_PX), position=apos, color=color.white, z=-0.04)
        aleft = self._win(79, 39, 0, wy)
        self._furnace_arrow = Entity(parent=self.screen_root, model="quad", texture=get_gui_texture("arrow"),
                                     scale=(22 * GUI_PX * pr, 9 * GUI_PX),
                                     position=(aleft[0], aleft[1]), origin=(-0.5, 0),
                                     color=color.white, z=-0.05)
        try:
            self._furnace_arrow.texture_scale = (max(0.001, pr), 1)
        except Exception:
            pass

    def _click_furnace_slot(self, attr, right):
        furn = self.ctrl.furnace
        inv = self.ctrl.player.inventory
        st = getattr(furn, attr)
        cur = inv.cursor_stack
        if not right:
            if cur is None:
                setattr(furn, attr, None)
                inv.cursor_stack = st
            elif st is None:
                setattr(furn, attr, cur)
                inv.cursor_stack = None
            elif st.item_id == cur.item_id and st.durability is None:
                space = st.max_stack - st.count
                move = min(space, cur.count)
                st.count += move
                cur.count -= move
                if cur.count <= 0:
                    inv.cursor_stack = None
            else:
                setattr(furn, attr, cur)
                inv.cursor_stack = st
        else:
            if cur is None and st is not None:
                half = (st.count + 1) // 2
                inv.cursor_stack = ItemStack(st.item_id, half, st.durability)
                st.count -= half
                if st.count <= 0:
                    setattr(furn, attr, None)
            elif cur is not None:
                if st is None:
                    setattr(furn, attr, ItemStack(cur.item_id, 1, cur.durability))
                    cur.count -= 1
                    if cur.count <= 0:
                        inv.cursor_stack = None
                elif st.item_id == cur.item_id and st.count < st.max_stack:
                    st.count += 1
                    cur.count -= 1
                    if cur.count <= 0:
                        inv.cursor_stack = None

    # recipe book ---------------------------------------------------------
    def _build_recipe_book(self, wy):
        from ursina import Entity, color
        inv = self.ctrl.player.inventory
        cs = self.ctrl.crafting
        bx = -(WIN_W / 2 + 66) * GUI_PX
        Entity(parent=self.screen_root, model="quad", texture=get_container_texture(),
               scale=(128 * GUI_PX, WIN_H * GUI_PX), position=(bx, wy), color=color.white, z=0.09)
        ShadowText(self.screen_root, "Recipe Book", (bx - 58 * GUI_PX, wy + (WIN_H / 2 - 12) * GUI_PX),
                   scale=0.8, color=color.rgb(0.25, 0.25, 0.25), origin=(-0.5, 0), z=-0.05)

        craftable = [r for r in cs.recipes if cs.can_craft(r, inv)]
        per_page = 8
        max_page = max(0, (len(craftable) - 1) // per_page) if craftable else 0
        self.recipe_page = max(0, min(max_page, self.recipe_page))
        page = craftable[self.recipe_page * per_page:(self.recipe_page + 1) * per_page]

        from ursina import Button, Entity as UEntity
        for idx, rec in enumerate(page):
            ry = 24 + idx * 17
            row_y = wy + (WIN_H / 2 - ry - 8) * GUI_PX
            row_btn = Button(parent=self.screen_root, text="", model="quad",
                             texture=get_gui_texture("slot"), position=(bx, row_y),
                             scale=(118 * GUI_PX, 16 * GUI_PX), color=color.rgb(0.85, 0.85, 0.85), z=-0.03)
            row_btn.highlight_color = color.white

            def fill(r_id=rec.id):
                self._autofill_grid(r_id)

            row_btn.on_click = fill
            UEntity(parent=self.screen_root, model="quad", texture=get_item_icon_texture(rec.result_item),
                    scale=(14 * GUI_PX, 14 * GUI_PX), position=(bx - 48 * GUI_PX, row_y), color=color.white, z=-0.06)
            ShadowText(self.screen_root, rec.name, (bx - 38 * GUI_PX, row_y), scale=0.55,
                       color=color.rgb(0.15, 0.15, 0.15), origin=(-0.5, 0), z=-0.06)

        ShadowText(self.screen_root, f"Page {self.recipe_page + 1}/{max_page + 1}", (bx, wy - (WIN_H / 2 - 12) * GUI_PX),
                   scale=0.65, color=color.rgb(0.25, 0.25, 0.25), origin=(0, 0), z=-0.05)
        self._mc_button(self.screen_root, "Prev", (bx - 34 * GUI_PX, wy - (WIN_H / 2 - 12) * GUI_PX), (0.055, 0.035),
                        lambda: (setattr(self, "recipe_page", max(0, self.recipe_page - 1)),
                                 self.show_inventory_screen(self.inv_tab, table=self.inv_table)), text_scale=0.6)
        self._mc_button(self.screen_root, "Next", (bx + 34 * GUI_PX, wy - (WIN_H / 2 - 12) * GUI_PX), (0.055, 0.035),
                        lambda: (setattr(self, "recipe_page", min(max_page, self.recipe_page + 1)),
                                 self.show_inventory_screen(self.inv_tab, table=self.inv_table)), text_scale=0.6)

    def _autofill_grid(self, recipe_id: str) -> None:
        """Recipe-book behaviour: move ingredients from inventory into the crafting grid."""
        inv = self.ctrl.player.inventory
        cs = self.ctrl.crafting
        rec = cs.by_id.get(recipe_id)
        if rec is None:
            return
        grid_size = 3 if self.inv_table else 2
        total = sum(rec.ingredients.values())
        if rec.requires_table and not self.inv_table:
            self.show_notification("Requires a Crafting Table!", 2.0)
            return
        if total > grid_size * grid_size:
            self.show_notification("Recipe needs a bigger grid!", 2.0)
            return
        if not cs.can_craft(rec, inv):
            return
        self._return_grid_to_inventory()
        idx = 0
        for item_key, cnt in rec.ingredients.items():
            for _ in range(cnt):
                inv.remove_item(item_key, 1)
                self.craft_grid[idx] = ItemStack(item_key, 1)
                idx += 1
        play_game_sound("craft", self.ctrl.settings)
        self.show_inventory_screen("crafting", table=self.inv_table)
