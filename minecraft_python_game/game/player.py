"""
First-Person Player Controller:
Handles movement (W/A/S/D, Sprint, Jump, Swim), smooth camera look with
Minecraft-style view bobbing and sprint FOV kick, 3D voxel AABB collision,
block mining (with destroy-stage crack overlay) & placement, an animated
first-person arm/held-item viewmodel (swing / eat / bob), experience levels,
health, hunger, eating, death, and respawning.
"""

import math
from typing import Any, Dict, Optional, Tuple

from game.assets_gen import (
    box_mesh_data,
    get_item_icon_texture,
    make_textured_box,
    play_game_sound,
)
from game.blocks import (
    AIR,
    BEDROCK,
    CHEST,
    CRAFTING_TABLE,
    FURNACE,
    WATER,
    BLOCKS_BY_ID,
    calculate_mining_time,
    get_block_by_id,
    get_item_def,
)
from game.inventory import Inventory
from game.terrain import CHUNK_HEIGHT
from game.world import VoxelHit, World

SKIN_COLOR = (0.94, 0.72, 0.56)


class Player:
    """First-person survival player with voxel AABB physics, inventory, health, hunger, XP."""

    HALF_WIDTH = 0.30
    HEIGHT = 1.74
    EYE_HEIGHT = 1.56

    WALK_SPEED = 4.6
    SPRINT_SPEED = 7.0
    SWIM_SPEED = 2.9
    JUMP_VELOCITY = 7.7
    GRAVITY = 22.0
    REACH_DISTANCE = 5.8

    def __init__(self, world: World, spawn_pos: Tuple[float, float, float] = (8.5, 25.0, 8.5)):
        self.world = world
        self.spawn_pos = (float(spawn_pos[0]), float(spawn_pos[1]), float(spawn_pos[2]))
        self.x, self.y, self.z = self.spawn_pos
        self.vx: float = 0.0
        self.vy: float = 0.0
        self.vz: float = 0.0

        self.yaw: float = 0.0
        self.pitch: float = 10.0

        self.on_ground: bool = False
        self.in_water: bool = False
        self.head_underwater: bool = False
        self.is_sprinting: bool = False
        self.fall_distance: float = 0.0

        # Survival stats
        self.max_health: float = 20.0
        self.health: float = 20.0
        self.max_hunger: float = 20.0
        self.hunger: float = 20.0
        self.is_dead: bool = False
        self.death_reason: str = ""
        self.hurt_flash_timer: float = 0.0
        self._regen_timer: float = 0.0
        self._starve_timer: float = 0.0
        self._step_sound_timer: float = 0.0

        # Experience (Minecraft-style levels)
        self.xp_level: int = 0
        self.xp_points: float = 0.0  # points accumulated within the current level

        self.inventory = Inventory()

        # Block targeting & mining progress
        self.targeted_hit: VoxelHit = VoxelHit(hit=False)
        self.mining_block_pos: Optional[Tuple[int, int, int]] = None
        self.mining_timer: float = 0.0
        self.mining_required_time: float = 1.0

        # Viewmodel / selection entities
        self.selection_box = None
        self.crack_entity = None
        self._crack_stage: int = -1
        self.arm_root = None
        self.arm_box = None
        self.hand_box = None
        self.held_entity = None
        self._last_held_key: Optional[str] = "__init__"
        self._swing_anim: float = 0.0
        self._eat_anim: float = 0.0
        self._bob_phase: float = 0.0
        self._bob_strength: float = 0.0
        self._current_fov: float = 90.0

        self._init_visual_entities()
        self.sync_camera()

    # ------------------------------------------------------------------ basics
    @property
    def xp_progress(self) -> float:
        """0..1 progress toward the next experience level."""
        return max(0.0, min(1.0, self.xp_points / max(1.0, self.xp_needed_for_level(self.xp_level))))

    @property
    def position(self) -> Tuple[float, float, float]:
        return (self.x, self.y, self.z)

    @position.setter
    def position(self, pos: Tuple[float, float, float]) -> None:
        self.x, self.y, self.z = float(pos[0]), float(pos[1]), float(pos[2])
        self.sync_camera()

    def get_eye_position(self) -> Tuple[float, float, float]:
        return (self.x, self.y + self.EYE_HEIGHT, self.z)

    def get_look_direction(self) -> Tuple[float, float, float]:
        yaw_rad = math.radians(self.yaw)
        pitch_rad = math.radians(self.pitch)
        cos_p = math.cos(pitch_rad)
        dx = math.sin(yaw_rad) * cos_p
        dy = -math.sin(pitch_rad)
        dz = math.cos(yaw_rad) * cos_p
        return (dx, dy, dz)

    # --------------------------------------------------------------- experience
    @staticmethod
    def xp_needed_for_level(level: int) -> float:
        if level < 16:
            return 2.0 * level + 7
        if level < 31:
            return 5.0 * level - 38
        return 9.0 * level - 158

    def add_xp(self, amount: float) -> bool:
        """Add experience points; returns True when a level-up happened."""
        if amount <= 0:
            return False
        self.xp_points += float(amount)
        leveled = False
        while self.xp_points >= self.xp_needed_for_level(self.xp_level):
            self.xp_points -= self.xp_needed_for_level(self.xp_level)
            self.xp_level += 1
            leveled = True
        if leveled:
            play_game_sound("levelup")
        return leveled

    # ------------------------------------------------------------------ visuals
    def _init_visual_entities(self) -> None:
        try:
            from ursina import Entity, camera, color

            # Minecraft-style black block outline around the targeted block
            self.selection_box = make_textured_box(
                size=(1.005, 1.005, 1.005),
                tiles={"top": "selection", "bottom": "selection", "north": "selection",
                       "south": "selection", "east": "selection", "west": "selection"},
            )
            self.selection_box.enabled = False

            # Destroy-stage crack overlay (mesh swapped per stage)
            self.crack_entity = Entity(model=None, enabled=False)

            # First-person arm + hand attached to the camera
            self.arm_root = Entity(parent=camera, position=(0.42, -0.40, 0.62), rotation=(6, -14, -6))
            self.arm_box = Entity(parent=self.arm_root, model="cube", scale=(0.115, 0.115, 0.42),
                                  position=(0, 0, 0.16), color=color.rgb(*SKIN_COLOR))
            self.hand_box = Entity(parent=self.arm_root, model="cube", scale=(0.13, 0.13, 0.13),
                                   position=(0, 0.0, 0.42), color=color.rgb(*SKIN_COLOR))
            self.held_entity = Entity(parent=self.arm_root, position=(0, 0.06, 0.48), enabled=True)
        except Exception:
            pass

    def sync_camera(self) -> None:
        """Sync the Ursina camera to eye position + view-bob offset."""
        try:
            from ursina import camera
            yaw_rad = math.radians(self.yaw)
            rx, rz = math.cos(yaw_rad), -math.sin(yaw_rad)
            lateral = math.sin(self._bob_phase) * 0.035 * self._bob_strength
            vertical = -abs(math.cos(self._bob_phase)) * 0.04 * self._bob_strength
            camera.position = (
                self.x + rx * lateral,
                self.y + self.EYE_HEIGHT + vertical,
                self.z + rz * lateral,
            )
            camera.rotation = (self.pitch, self.yaw, 0.0)
        except Exception:
            pass

    def rotate_view(self, delta_yaw: float, delta_pitch: float) -> None:
        self.yaw = (self.yaw + float(delta_yaw)) % 360.0
        self.pitch = max(-89.0, min(89.0, self.pitch + float(delta_pitch)))
        self.sync_camera()

    def trigger_swing(self) -> None:
        self._swing_anim = 1.0

    def update_held_visual(self) -> None:
        """Rebuild the first-person held item model when the hotbar selection changes."""
        if self.held_entity is None:
            return
        held_key = self.inventory.get_selected_item_key()
        if held_key == self._last_held_key:
            return
        self._last_held_key = held_key

        try:
            from ursina import Entity, Mesh, color, destroy

            # clear previous held model children
            for child in list(self.held_entity.children):
                destroy(child)
            self.held_entity.texture = None

            if held_key is None:
                # Bare fist is the hand box itself; nothing extra to show
                self.held_entity.enabled = True
                return

            idef = get_item_def(held_key)
            if idef is not None and idef.category == "block" and idef.block_id in BLOCKS_BY_ID:
                bdef = BLOCKS_BY_ID[idef.block_id]
                side = bdef.faces.get("side", "stone")
                tiles = {
                    "top": bdef.faces.get("top", side),
                    "bottom": bdef.faces.get("bottom", side),
                    "north": bdef.faces.get("north", side),
                    "south": bdef.faces.get("south", side),
                    "east": bdef.faces.get("east", side),
                    "west": bdef.faces.get("west", side),
                }
                box = make_textured_box(parent=self.held_entity, size=(0.26, 0.26, 0.26), tiles=tiles,
                                        position=(0, 0.02, 0.06), rotation=(0, 42, 0))
                self.held_entity.enabled = True
            elif idef is not None and idef.tool_type in ("pickaxe", "axe", "sword"):
                tex = get_item_icon_texture(held_key)
                Entity(parent=self.held_entity, model="quad", texture=tex, double_sided=True,
                       scale=(0.42, 0.42), position=(0.02, 0.10, 0.05), rotation=(12, 0, -38))
                self.held_entity.enabled = True
            else:
                tex = get_item_icon_texture(held_key)
                Entity(parent=self.held_entity, model="quad", texture=tex, double_sided=True,
                       scale=(0.30, 0.30), position=(0, 0.08, 0.05), rotation=(8, 0, -12))
                self.held_entity.enabled = True
        except Exception:
            pass

    def _update_viewmodel(self, dt: float, moving: bool) -> None:
        """Swing / eat / bob animations for the first-person arm."""
        if self.arm_root is None:
            return
        try:
            # swing arc (mining / attacking / placing)
            if self._swing_anim > 0.0:
                self._swing_anim = max(0.0, self._swing_anim - dt * 3.6)
            p = 1.0 - self._swing_anim
            swing = math.sin(min(1.0, p) * math.pi)
            rot_x = 6 - swing * 62.0
            rot_y = -14 + swing * 34.0
            pos_x = 0.42 - swing * 0.16
            pos_y = -0.40 - swing * 0.10

            # eating wiggle
            if self._eat_anim > 0.0:
                self._eat_anim = max(0.0, self._eat_anim - dt)
                w = math.sin(self._eat_anim * 34.0) * 0.035
                rot_x += 26.0
                pos_y += 0.16 + w
                pos_x -= 0.10

            # walking bob
            bob_x = math.sin(self._bob_phase) * 0.045 * self._bob_strength
            bob_y = -abs(math.cos(self._bob_phase)) * 0.05 * self._bob_strength

            self.arm_root.rotation = (rot_x, rot_y, -6 + swing * 12.0)
            self.arm_root.position = (pos_x + bob_x, pos_y + bob_y, 0.62)
        except Exception:
            pass

    def _update_crack_overlay(self) -> None:
        """Show Minecraft destroy-stage cracks on the block being mined."""
        if self.crack_entity is None:
            return
        prog = self.mining_progress
        if prog <= 0.02 or not self.targeted_hit.hit:
            self.crack_entity.enabled = False
            self._crack_stage = -1
            return
        stage = min(4, int(prog * 5.0))
        bx, by, bz = self.targeted_hit.block_pos
        if stage != self._crack_stage:
            self._crack_stage = stage
            try:
                from ursina import Mesh
                from game.assets_gen import get_atlas_texture
                tile = f"crack_{stage}"
                tiles = {k: tile for k in ("top", "bottom", "north", "south", "east", "west")}
                verts, tris, uvs, cols = box_mesh_data(tiles, (1.01, 1.01, 1.01))
                self.crack_entity.model = Mesh(vertices=verts, triangles=tris, uvs=uvs, colors=cols, static=True)
                self.crack_entity.texture = get_atlas_texture()
                self.crack_entity.double_sided = True
            except Exception:
                return
        self.crack_entity.position = (bx + 0.5, by + 0.5, bz + 0.5)
        self.crack_entity.enabled = True

    # ---------------------------------------------------------------- collision
    def _collides_aabb(self, px: float, py: float, pz: float) -> bool:
        hw = self.HALF_WIDTH
        min_bx = math.floor(px - hw)
        max_bx = math.floor(px + hw - 1e-5)
        min_by = math.floor(py)
        max_by = math.floor(py + self.HEIGHT - 1e-5)
        min_bz = math.floor(pz - hw)
        max_bz = math.floor(pz + hw - 1e-5)
        for bx in range(min_bx, max_bx + 1):
            for by in range(min_by, max_by + 1):
                for bz in range(min_bz, max_bz + 1):
                    if self.world.is_solid(bx, by, bz):
                        return True
        return False

    def block_intersects_player(self, bx: int, by: int, bz: int) -> bool:
        hw = self.HALF_WIDTH - 0.02
        p_min_x, p_max_x = self.x - hw, self.x + hw
        p_min_y, p_max_y = self.y + 0.02, self.y + self.HEIGHT - 0.02
        p_min_z, p_max_z = self.z - hw, self.z + hw
        return (
            p_max_x > bx and p_min_x < bx + 1
            and p_max_y > by and p_min_y < by + 1
            and p_max_z > bz and p_min_z < bz + 1
        )

    def move_and_collide(self, move_dx: float, move_dz: float, dt: float, jump_pressed: bool = False, settings=None) -> None:
        if self.is_dead:
            return
        dt = min(0.05, max(0.0, float(dt)))

        bx_center = math.floor(self.x)
        bz_center = math.floor(self.z)
        feet_water = self.world.is_water(bx_center, math.floor(self.y + 0.1), bz_center)
        waist_water = self.world.is_water(bx_center, math.floor(self.y + 0.85), bz_center)
        was_in_water = self.in_water
        self.in_water = feet_water or waist_water
        self.head_underwater = self.world.is_water(bx_center, math.floor(self.y + self.EYE_HEIGHT), bz_center)
        if self.in_water and not was_in_water:
            play_game_sound("splash", settings)

        if self.in_water:
            speed = self.SWIM_SPEED
            self.fall_distance = 0.0
        elif self.is_sprinting and self.hunger > 2.0:
            speed = self.SPRINT_SPEED
        else:
            speed = self.WALK_SPEED

        self.vx = move_dx * speed
        self.vz = move_dz * speed

        if self.in_water:
            if jump_pressed:
                self.vy = 3.8
            else:
                self.vy = max(-3.2, self.vy - 6.5 * dt)
        else:
            if jump_pressed and self.on_ground:
                self.vy = self.JUMP_VELOCITY
                self.on_ground = False
                if self.world.difficulty != "Peaceful":
                    self.hunger = max(0.0, self.hunger - 0.05)
            self.vy = max(-32.0, self.vy - self.GRAVITY * dt)

        new_x = self.x + self.vx * dt
        if not self._collides_aabb(new_x, self.y, self.z):
            self.x = new_x
        else:
            self.vx = 0.0

        new_z = self.z + self.vz * dt
        if not self._collides_aabb(self.x, self.y, new_z):
            self.z = new_z
        else:
            self.vz = 0.0

        dy = self.vy * dt
        new_y = self.y + dy
        if not self._collides_aabb(self.x, new_y, self.z):
            if dy < 0.0 and not self.in_water:
                self.fall_distance += abs(dy)
            self.y = new_y
            self.on_ground = False
        else:
            if self.vy < 0.0:
                self.y = float(math.floor(self.y + 0.05))
                while self._collides_aabb(self.x, self.y, self.z) and self.y < CHUNK_HEIGHT:
                    self.y += 0.05
                self.on_ground = True
                if self.fall_distance > 4.2 and not self.in_water and self.world.difficulty != "Peaceful":
                    dmg = (self.fall_distance - 3.8) * 1.6
                    self.take_damage(dmg, source="Fall", settings=settings)
                self.fall_distance = 0.0
            elif self.vy > 0.0:
                self.fall_distance = 0.0
            self.vy = 0.0

        if self.y < -5.0:
            self.y = float(self.spawn_pos[1])
            self.vy = 0.0
            self.fall_distance = 0.0

        # Footsteps + view bob phase
        horiz_speed = math.sqrt(self.vx * self.vx + self.vz * self.vz)
        if self.on_ground and horiz_speed > 0.5:
            self._bob_phase += dt * horiz_speed * 1.9
            self._bob_strength = min(1.0, self._bob_strength + dt * 8.0)
            self._step_sound_timer -= dt
            if self._step_sound_timer <= 0.0:
                self._step_sound_timer = 0.36 if self.is_sprinting else 0.48
                play_game_sound("step", settings)
        else:
            self._bob_strength = max(0.0, self._bob_strength - dt * 8.0)

        # Sprint FOV kick (Minecraft-style)
        try:
            from ursina import camera
            base_fov = float(getattr(settings, "fov", 90) or 90) if settings is not None else 90.0
            target = base_fov * (1.10 if (self.is_sprinting and horiz_speed > 0.5) else 1.0)
            self._current_fov += (target - self._current_fov) * min(1.0, dt * 10.0)
            camera.fov = self._current_fov
        except Exception:
            pass

        self.sync_camera()

    # ------------------------------------------------------------------ mining
    def update_raycast_and_selection(self) -> VoxelHit:
        self.targeted_hit = self.world.raycast_voxel(
            self.get_eye_position(),
            self.get_look_direction(),
            max_dist=self.REACH_DISTANCE,
        )
        if self.selection_box is not None:
            try:
                if self.targeted_hit.hit:
                    bx, by, bz = self.targeted_hit.block_pos
                    self.selection_box.position = (bx + 0.5, by + 0.5, bz + 0.5)
                    self.selection_box.enabled = True
                else:
                    self.selection_box.enabled = False
            except Exception:
                pass

        if not self.targeted_hit.hit or self.targeted_hit.block_pos != self.mining_block_pos:
            self.mining_block_pos = self.targeted_hit.block_pos if self.targeted_hit.hit else None
            self.mining_timer = 0.0
            if self.targeted_hit.hit:
                self.mining_required_time = calculate_mining_time(
                    self.targeted_hit.block_id,
                    self.inventory.get_selected_item_key(),
                )
            else:
                self.mining_required_time = 1.0
        self._update_crack_overlay()
        return self.targeted_hit

    @property
    def mining_progress(self) -> float:
        if not self.targeted_hit.hit or math.isinf(self.mining_required_time) or self.mining_required_time <= 0:
            return 0.0
        return min(1.0, max(0.0, self.mining_timer / self.mining_required_time))

    def mine_step(self, dt: float, settings=None) -> bool:
        if self.is_dead:
            return False
        self.update_raycast_and_selection()
        if not self.targeted_hit.hit:
            self.mining_timer = 0.0
            return False
        bid = self.targeted_hit.block_id
        bdef = get_block_by_id(bid)
        if bdef.unbreakable or bid == AIR or bid == WATER:
            self.mining_timer = 0.0
            return False
        held_key = self.inventory.get_selected_item_key()
        self.mining_required_time = calculate_mining_time(bid, held_key)
        self.mining_timer += float(dt)
        self.trigger_swing()
        self._update_crack_overlay()
        if self.mining_timer >= self.mining_required_time:
            return self.break_targeted_block(settings=settings)
        return False

    def break_targeted_block(self, settings=None) -> bool:
        if not self.targeted_hit.hit:
            self.update_raycast_and_selection()
        if not self.targeted_hit.hit:
            return False
        bx, by, bz = self.targeted_hit.block_pos
        bid = self.world.get_block(bx, by, bz)
        bdef = get_block_by_id(bid)
        if bdef.unbreakable or bid == AIR or bid == WATER:
            return False
        if not self.world.set_block(bx, by, bz, AIR):
            return False

        self.world.spawn_break_particles(bx, by, bz, bid)
        play_game_sound("dig", settings)
        play_game_sound("pop", settings)

        if bdef.drop_item:
            self.inventory.add_item(bdef.drop_item, bdef.drop_count)

        # Minecraft-style experience from mining ores
        xp_map = {9: 1, 10: 2, 11: 3, 12: 5}
        if bid in xp_map:
            self.add_xp(xp_map[bid])

        self.inventory.damage_selected_tool(1)
        self.mining_timer = 0.0
        self.mining_block_pos = None
        self._crack_stage = -1
        if self.crack_entity is not None:
            self.crack_entity.enabled = False
        self.update_raycast_and_selection()
        self.update_held_visual()
        return True

    def place_selected_block(self, settings=None) -> Optional[str]:
        if self.is_dead:
            return None
        self.update_raycast_and_selection()
        held_stack = self.inventory.get_selected_stack()
        held_def = held_stack.item_def if held_stack else None

        if self.targeted_hit.hit and not self.is_sprinting:
            t_bid = self.targeted_hit.block_id
            if t_bid == CRAFTING_TABLE:
                return "crafting_table"
            if t_bid == FURNACE:
                return "furnace"
            if t_bid == CHEST:
                return "chest"

        if held_def is not None and held_def.category == "food":
            if self.eat_selected_food(settings=settings):
                return "ate"

        if held_def is None or held_def.block_id is None:
            return None
        if not self.targeted_hit.hit:
            return None

        px, py, pz = self.targeted_hit.place_pos
        if not (0 <= py < CHUNK_HEIGHT):
            return None
        existing = self.world.get_block(px, py, pz)
        if existing != AIR and existing != WATER:
            return None
        new_bdef = get_block_by_id(held_def.block_id)
        if new_bdef.solid and self.block_intersects_player(px, py, pz):
            return None
        if self.world.set_block(px, py, pz, held_def.block_id):
            self.inventory.consume_selected(1)
            self.trigger_swing()
            play_game_sound("place", settings)
            self.update_raycast_and_selection()
            self.update_held_visual()
            return "placed"
        return None

    def eat_selected_food(self, settings=None) -> bool:
        if self.is_dead:
            return False
        st = self.inventory.get_selected_stack()
        if st is None:
            return False
        idef = st.item_def
        if idef is None or idef.food_restore <= 0:
            return False
        if self.hunger >= self.max_hunger:
            return False
        self.hunger = min(self.max_hunger, self.hunger + float(idef.food_restore))
        self.inventory.consume_selected(1)
        self.trigger_swing()
        self._eat_anim = 0.7
        play_game_sound("eat", settings)
        self.update_held_visual()
        return True

    def take_damage(
        self,
        amount: float,
        source: str = "Damage",
        knockback_dir: Tuple[float, float] = (0.0, 0.0),
        settings=None,
    ) -> bool:
        if self.is_dead or amount <= 0.0:
            return False
        self.health = max(0.0, self.health - float(amount))
        self.hurt_flash_timer = 0.35
        self.vx += float(knockback_dir[0]) * 4.5
        self.vz += float(knockback_dir[1]) * 4.5
        if self.on_ground:
            self.vy = 3.2
        play_game_sound("hurt", settings)
        if self.health <= 0.0:
            self.health = 0.0
            self.is_dead = True
            self.death_reason = f"Slain by {source}" if source not in ("Fall", "Starvation") else source
            return True
        return False

    def respawn(self, keep_inventory: bool = True) -> None:
        self.health = self.max_health
        self.hunger = self.max_hunger
        self.is_dead = False
        self.death_reason = ""
        self.hurt_flash_timer = 0.0
        self.fall_distance = 0.0
        self.vx = self.vy = self.vz = 0.0
        if not keep_inventory:
            self.inventory.clear()
        self.spawn_pos = self.world.find_spawn_position(int(self.spawn_pos[0]), int(self.spawn_pos[2]))
        self.position = self.spawn_pos
        self.update_held_visual()

    def update_survival(self, dt: float, settings=None) -> None:
        if self.is_dead:
            return
        dt = min(0.1, max(0.0, float(dt)))
        if self.hurt_flash_timer > 0.0:
            self.hurt_flash_timer = max(0.0, self.hurt_flash_timer - dt)

        moving = math.sqrt(self.vx * self.vx + self.vz * self.vz) > 0.5
        self._update_viewmodel(dt, moving)
        self.update_held_visual()

        if self.world.difficulty == "Peaceful":
            self.hunger = min(self.max_hunger, self.hunger + dt * 0.5)
            self.health = min(self.max_health, self.health + dt * 0.5)
            return

        drain_rate = 0.045 if not self.is_sprinting else 0.14
        self.hunger = max(0.0, self.hunger - drain_rate * dt)

        if self.hunger >= 18.0 and self.health < self.max_health:
            self._regen_timer += dt
            if self._regen_timer >= 3.5:
                self._regen_timer = 0.0
                self.health = min(self.max_health, self.health + 1.0)
                self.hunger = max(0.0, self.hunger - 0.3)
        else:
            self._regen_timer = 0.0

        if self.hunger <= 0.0:
            self._starve_timer += dt
            if self._starve_timer >= 3.5:
                self._starve_timer = 0.0
                self.take_damage(1.0, source="Starvation", settings=settings)
        else:
            self._starve_timer = 0.0

    # -------------------------------------------------------------------- save
    def to_dict(self) -> Dict[str, Any]:
        return {
            "position": [self.x, self.y, self.z],
            "spawn_pos": list(self.spawn_pos),
            "yaw": self.yaw,
            "pitch": self.pitch,
            "health": self.health,
            "hunger": self.hunger,
            "xp_level": self.xp_level,
            "xp_points": self.xp_points,
            "selected_slot": self.inventory.selected_slot,
            "inventory": self.inventory.to_list(),
        }

    def load_from_dict(self, data: Optional[Dict[str, Any]]) -> None:
        if not data or not isinstance(data, dict):
            return
        pos = data.get("position")
        if isinstance(pos, list) and len(pos) == 3:
            self.x, self.y, self.z = float(pos[0]), float(pos[1]), float(pos[2])
        spos = data.get("spawn_pos")
        if isinstance(spos, list) and len(spos) == 3:
            self.spawn_pos = (float(spos[0]), float(spos[1]), float(spos[2]))
        self.yaw = float(data.get("yaw", 0.0))
        self.pitch = float(data.get("pitch", 10.0))
        self.health = max(1.0, min(self.max_health, float(data.get("health", 20.0))))
        self.hunger = max(0.0, min(self.max_hunger, float(data.get("hunger", 20.0))))
        self.xp_level = int(data.get("xp_level", 0))
        self.xp_points = float(data.get("xp_points", data.get("xp_progress", 0.0)))
        self.inventory.load_from_list(data.get("inventory", []))
        self.inventory.select_slot(int(data.get("selected_slot", 0)))
        self.sync_camera()
        self.update_held_visual()

    def cleanup(self) -> None:
        try:
            from ursina import destroy
            for ent in (self.selection_box, self.crack_entity, self.arm_root):
                if ent is not None:
                    destroy(ent)
            self.selection_box = None
            self.crack_entity = None
            self.arm_root = None
            self.held_entity = None
        except Exception:
            pass
