"""
AI Mobs system: Passive (Pig, Cow, Sheep) and Hostile (Zombie, Skeleton, Creeper).
Mobs are built from textured voxel boxes (per-face atlas UVs, Minecraft model
proportions) with joint-based limb swing animations, wandering/chase AI, voxel
collision, health, damage, knockback, item drops, creeper fuse & explosion,
and day/night spawning rules.
"""

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from game.assets_gen import make_textured_box, play_game_sound
from game.combat import DIFFICULTY_DAMAGE_MULTIPLIER
from game.terrain import CHUNK_HEIGHT, SEA_LEVEL


@dataclass(frozen=True)
class MobConfig:
    mob_type: str
    name: str
    hostile: bool
    max_health: float
    move_speed: float
    detect_range: float
    attack_range: float
    attack_damage: float
    attack_cooldown: float
    drops: List[Tuple[str, int, int]]  # (item_key, min_count, max_count)
    xp: int = 5
    body_color: Tuple[float, float, float] = (0.8, 0.8, 0.8)
    head_color: Tuple[float, float, float] = (0.8, 0.8, 0.8)
    limb_color: Tuple[float, float, float] = (0.7, 0.7, 0.7)
    explosive: bool = False


MOB_CONFIGS: Dict[str, MobConfig] = {
    "pig": MobConfig(
        mob_type="pig", name="Pig", hostile=False,
        max_health=10.0, move_speed=2.1, detect_range=10.0,
        attack_range=0.0, attack_damage=0.0, attack_cooldown=1.5,
        drops=[("raw_pork", 1, 2)], xp=3,
        body_color=(0.95, 0.65, 0.68), head_color=(0.98, 0.70, 0.73), limb_color=(0.88, 0.55, 0.58),
    ),
    "cow": MobConfig(
        mob_type="cow", name="Cow", hostile=False,
        max_health=12.0, move_speed=2.0, detect_range=10.0,
        attack_range=0.0, attack_damage=0.0, attack_cooldown=1.5,
        drops=[("raw_beef", 1, 2)], xp=3,
        body_color=(0.42, 0.28, 0.18), head_color=(0.48, 0.34, 0.22), limb_color=(0.35, 0.22, 0.14),
    ),
    "sheep": MobConfig(
        mob_type="sheep", name="Sheep", hostile=False,
        max_health=10.0, move_speed=2.0, detect_range=10.0,
        attack_range=0.0, attack_damage=0.0, attack_cooldown=1.5,
        drops=[("wool", 1, 2), ("raw_mutton", 0, 0)], xp=3,
        body_color=(0.9, 0.9, 0.9), head_color=(0.85, 0.72, 0.66), limb_color=(0.88, 0.88, 0.88),
    ),
    "zombie": MobConfig(
        mob_type="zombie", name="Zombie", hostile=True,
        max_health=20.0, move_speed=2.7, detect_range=18.0,
        attack_range=1.95, attack_damage=3.0, attack_cooldown=1.15,
        drops=[("rotten_flesh", 1, 2), ("iron_ingot", 0, 1)], xp=5,
        body_color=(0.18, 0.48, 0.62), head_color=(0.34, 0.62, 0.32), limb_color=(0.24, 0.26, 0.52),
    ),
    "skeleton": MobConfig(
        mob_type="skeleton", name="Skeleton", hostile=True,
        max_health=16.0, move_speed=2.85, detect_range=20.0,
        attack_range=2.1, attack_damage=3.0, attack_cooldown=1.45,
        drops=[("bone", 1, 2), ("coal", 0, 1)], xp=5,
        body_color=(0.86, 0.86, 0.82), head_color=(0.92, 0.92, 0.88), limb_color=(0.78, 0.78, 0.74),
    ),
    "creeper": MobConfig(
        mob_type="creeper", name="Creeper", hostile=True,
        max_health=18.0, move_speed=2.5, detect_range=14.0,
        attack_range=2.6, attack_damage=0.0, attack_cooldown=1.0,
        drops=[("gunpowder", 1, 2)], xp=5,
        body_color=(0.24, 0.66, 0.24), head_color=(0.24, 0.66, 0.24), limb_color=(0.2, 0.55, 0.2),
        explosive=True,
    ),
}

# Drop tables may reference optional items that do not exist; filtered at runtime.
from game.blocks import get_item_def as _get_item_def


def _valid_drops(drops):
    return [d for d in drops if _get_item_def(d[0]) is not None]


class Mob:
    """Single AI mob with a textured articulated voxel model, physics and AI."""

    def __init__(self, mob_type: str, position: Tuple[float, float, float], world):
        self.config: MobConfig = MOB_CONFIGS.get(mob_type, MOB_CONFIGS["pig"])
        self.mob_type = self.config.mob_type
        self.name = self.config.name
        self.hostile = self.config.hostile
        self.world = world

        self.x, self.y, self.z = float(position[0]), float(position[1]), float(position[2])
        self.vx: float = 0.0
        self.vy: float = 0.0
        self.vz: float = 0.0
        self.yaw: float = random.uniform(0.0, 360.0)

        self.max_health: float = self.config.max_health
        self.health: float = self.max_health
        self.dead: bool = False
        self.hit_radius: float = 0.85

        # AI timers
        self.wander_timer: float = random.uniform(1.0, 3.5)
        self.wander_dir: Tuple[float, float] = (0.0, 0.0)
        self.flee_timer: float = 0.0
        self.attack_timer: float = 0.0
        self.hurt_flash_timer: float = 0.0
        self.anim_time: float = random.uniform(0.0, 10.0)
        self.fuse: float = -1.0  # creeper hiss timer (-1 = not lit)
        self._hissed: bool = False

        # Visual entities
        self.root_entity = None
        self.part_entities: List[object] = []
        self.joint_entities: List[Tuple[object, str, float]] = []  # (joint, kind, phase)
        self.hp_bar_bg = None
        self.hp_bar_fg = None
        self._build_visual_model()

    @property
    def position(self) -> Tuple[float, float, float]:
        return (self.x, self.y, self.z)

    @position.setter
    def position(self, val: Tuple[float, float, float]) -> None:
        self.x, self.y, self.z = float(val[0]), float(val[1]), float(val[2])
        self._sync_visuals()

    # ------------------------------------------------------------------ model
    def _build_visual_model(self) -> None:
        try:
            from ursina import Entity, color

            self.root_entity = Entity(position=(self.x, self.y, self.z), rotation_y=self.yaw)
            mt = self.mob_type
            joints: List[Tuple[object, str, float]] = []
            parts: List[object] = []

            def limb(px_, py_, pz_, size, tiles, kind, phase, fixed_rot=0.0):
                joint = Entity(parent=self.root_entity, position=(px_, py_, pz_))
                box = make_textured_box(parent=joint, size=size, tiles=tiles, position=(0, -size[1] / 2.0, 0))
                if fixed_rot:
                    joint.rotation_x = fixed_rot
                joints.append((joint, kind, phase))
                parts.append(box)
                return box

            if mt == "pig":
                parts.append(make_textured_box(self.root_entity, (0.625, 0.5, 0.75), {"top": "pig_side", "bottom": "pig_side", "north": "pig_side", "south": "pig_side", "east": "pig_side", "west": "pig_side"}, (0, 0.625, 0)))
                parts.append(make_textured_box(self.root_entity, (0.5, 0.5, 0.5), {"north": "pig_face", "top": "pig_side", "bottom": "pig_side", "south": "pig_side", "east": "pig_side", "west": "pig_side"}, (0, 0.72, 0.6)))
                parts.append(make_textured_box(self.root_entity, (0.25, 0.19, 0.06), {"north": "pig_face", "top": "pig_side", "bottom": "pig_side", "south": "pig_side", "east": "pig_side", "west": "pig_side"}, (0, 0.66, 0.87)))
                for sx in (-0.19, 0.19):
                    for sz in (-0.25, 0.25):
                        limb(sx, 0.375, sz, (0.25, 0.375, 0.25), {"top": "pig_side", "north": "pig_side", "south": "pig_side", "east": "pig_side", "west": "pig_side", "bottom": "pig_side"}, "leg", 0.0 if (sx > 0) != (sz > 0) else math.pi)
                bar_y = 1.25
            elif mt == "cow":
                parts.append(make_textured_box(self.root_entity, (0.68, 0.72, 0.95), {"top": "cow_side", "bottom": "cow_side", "north": "cow_side", "south": "cow_side", "east": "cow_side", "west": "cow_side"}, (0, 0.82, 0)))
                parts.append(make_textured_box(self.root_entity, (0.5, 0.5, 0.5), {"north": "cow_face", "top": "cow_side", "bottom": "cow_side", "south": "cow_side", "east": "cow_side", "west": "cow_side"}, (0, 1.06, 0.66)))
                for sx in (-0.22, 0.22):
                    for sz in (-0.34, 0.34):
                        limb(sx, 0.46, sz, (0.25, 0.46, 0.25), {"top": "cow_side", "north": "cow_side", "south": "cow_side", "east": "cow_side", "west": "cow_side", "bottom": "cow_side"}, "leg", 0.0 if (sx > 0) != (sz > 0) else math.pi)
                bar_y = 1.55
            elif mt == "sheep":
                parts.append(make_textured_box(self.root_entity, (0.625, 0.625, 0.95), {"top": "sheep_side", "bottom": "sheep_side", "north": "sheep_side", "south": "sheep_side", "east": "sheep_side", "west": "sheep_side"}, (0, 0.82, 0)))
                parts.append(make_textured_box(self.root_entity, (0.44, 0.44, 0.44), {"north": "sheep_face", "top": "sheep_side", "bottom": "sheep_face", "south": "sheep_face", "east": "sheep_face", "west": "sheep_face"}, (0, 1.02, 0.62)))
                for sx in (-0.2, 0.2):
                    for sz in (-0.32, 0.32):
                        limb(sx, 0.5, sz, (0.22, 0.5, 0.22), {"top": "sheep_side", "north": "sheep_side", "south": "sheep_side", "east": "sheep_side", "west": "sheep_side", "bottom": "sheep_side"}, "leg", 0.0 if (sx > 0) != (sz > 0) else math.pi)
                bar_y = 1.5
            elif mt in ("zombie", "skeleton"):
                head_t = "zombie_head" if mt == "zombie" else "skeleton_face"
                body_t = "zombie_body" if mt == "zombie" else "skeleton_body"
                leg_t = "zombie_legs" if mt == "zombie" else "skeleton_body"
                arm_t = "zombie_arm" if mt == "zombie" else "skeleton_body"
                parts.append(make_textured_box(self.root_entity, (0.5, 0.75, 0.25), {"top": body_t, "bottom": body_t, "north": body_t, "south": body_t, "east": body_t, "west": body_t}, (0, 1.125, 0)))
                parts.append(make_textured_box(self.root_entity, (0.5, 0.5, 0.5), {"north": head_t, "top": head_t, "bottom": head_t, "south": head_t, "east": head_t, "west": head_t}, (0, 1.75, 0)))
                arm_rot = -80.0 if mt == "zombie" else -18.0
                for sx in (-0.3125, 0.3125):
                    limb(sx, 1.44, 0.0, (0.25, 0.72, 0.25), {"top": arm_t, "north": arm_t, "south": arm_t, "east": arm_t, "west": arm_t, "bottom": arm_t}, "arm", 0.0 if sx > 0 else math.pi, arm_rot)
                for sx in (-0.125, 0.125):
                    limb(sx, 0.75, 0.0, (0.25, 0.75, 0.25), {"top": leg_t, "north": leg_t, "south": leg_t, "east": leg_t, "west": leg_t, "bottom": leg_t}, "leg", math.pi if sx > 0 else 0.0)
                bar_y = 2.15
            else:  # creeper
                parts.append(make_textured_box(self.root_entity, (0.5, 0.75, 0.25), {"top": "creeper_skin", "bottom": "creeper_skin", "north": "creeper_skin", "south": "creeper_skin", "east": "creeper_skin", "west": "creeper_skin"}, (0, 0.75, 0)))
                parts.append(make_textured_box(self.root_entity, (0.5, 0.5, 0.5), {"north": "creeper_face", "top": "creeper_skin", "bottom": "creeper_skin", "south": "creeper_skin", "east": "creeper_skin", "west": "creeper_skin"}, (0, 1.375, 0)))
                for sx in (-0.125, 0.125):
                    for sz in (-0.25, 0.25):
                        limb(sx, 0.375, sz, (0.25, 0.375, 0.25), {"top": "creeper_skin", "north": "creeper_skin", "south": "creeper_skin", "east": "creeper_skin", "west": "creeper_skin", "bottom": "creeper_skin"}, "leg", 0.0 if (sx > 0) != (sz > 0) else math.pi)
                bar_y = 1.85

            self.part_entities = parts
            self.joint_entities = joints

            # Floating overhead health indicator
            self.hp_bar_bg = Entity(parent=self.root_entity, model="cube", scale=(0.72, 0.07, 0.04), position=(0, bar_y, 0), color=color.rgb(0.18, 0.18, 0.20))
            self.hp_bar_fg = Entity(parent=self.root_entity, model="cube", scale=(0.70, 0.06, 0.05), position=(0, bar_y, 0),
                                    color=color.rgb(0.92, 0.22, 0.22) if self.hostile else color.rgb(0.25, 0.85, 0.35))
        except Exception:
            pass

    def _sync_visuals(self) -> None:
        if self.root_entity is not None:
            try:
                self.root_entity.position = (self.x, self.y, self.z)
                self.root_entity.rotation_y = self.yaw
                if self.hp_bar_fg is not None:
                    frac = max(0.0, min(1.0, self.health / max(1.0, self.max_health)))
                    self.hp_bar_fg.scale_x = 0.70 * frac
            except Exception:
                pass

    def _animate_limbs(self, move_mag: float, dt: float) -> None:
        if not self.joint_entities:
            return
        if move_mag > 0.2:
            self.anim_time += dt * move_mag * 4.2
        else:
            # ease back to rest pose
            self.anim_time += dt * 6.0
        amp = min(38.0, move_mag * 16.0)
        try:
            for joint, kind, phase in self.joint_entities:
                swing = math.sin(self.anim_time + phase) * amp
                if kind == "arm" and self.mob_type == "zombie":
                    joint.rotation_x = -80.0 + swing * 0.25
                elif kind == "arm":
                    joint.rotation_x = -18.0 + swing
                else:
                    joint.rotation_x = swing
        except Exception:
            pass

    # ----------------------------------------------------------------- combat
    def take_damage(
        self,
        amount: float,
        knockback_dir: Tuple[float, float] = (0.0, 0.0),
        knockback_strength: float = 6.0,
        attacker_player=None,
        settings=None,
    ) -> bool:
        if self.dead:
            return False
        self.health = max(0.0, self.health - float(amount))
        self.hurt_flash_timer = 0.22
        self.vx = float(knockback_dir[0]) * knockback_strength
        self.vz = float(knockback_dir[1]) * knockback_strength
        self.vy = 4.2
        if not self.hostile:
            self.flee_timer = 3.5
            self.wander_dir = (float(knockback_dir[0]), float(knockback_dir[1]))
        play_game_sound("hurt", settings)
        self._set_flash_color(True)
        self._sync_visuals()
        if self.health <= 0.0:
            self.die(attacker_player)
            return True
        return False

    def _set_flash_color(self, flashing: bool) -> None:
        if not self.part_entities:
            return
        try:
            from ursina import color
            c = color.rgb(1.0, 0.25, 0.25) if flashing else color.white
            for p in self.part_entities:
                p.color = c
        except Exception:
            pass

    def die(self, attacker_player=None) -> None:
        if self.dead:
            return
        self.dead = True
        if attacker_player is not None and hasattr(attacker_player, "inventory"):
            for item_key, min_c, max_c in _valid_drops(self.config.drops):
                cnt = random.randint(min_c, max_c)
                if cnt > 0:
                    attacker_player.inventory.add_item(item_key, cnt)
                    play_game_sound("pop", getattr(attacker_player, "_settings", None))
            if hasattr(attacker_player, "add_xp"):
                attacker_player.add_xp(self.config.xp)
        self.destroy_visuals()

    def destroy_visuals(self) -> None:
        try:
            from ursina import destroy
            if self.root_entity is not None:
                destroy(self.root_entity)
                self.root_entity = None
            self.part_entities.clear()
            self.joint_entities.clear()
        except Exception:
            self.root_entity = None

    # --------------------------------------------------------------------- AI
    def update(self, dt: float, player, settings=None) -> None:
        if self.dead:
            return
        dt = min(0.05, max(0.0, float(dt)))

        if self.hurt_flash_timer > 0.0:
            self.hurt_flash_timer -= dt
            if self.hurt_flash_timer <= 0.0:
                self._set_flash_color(False)
        if self.attack_timer > 0.0:
            self.attack_timer = max(0.0, self.attack_timer - dt)

        px, py, pz = player.position
        dx = px - self.x
        dy = py - self.y
        dz = pz - self.z
        horiz_dist = math.sqrt(dx * dx + dz * dz)
        full_dist = math.sqrt(dx * dx + dy * dy + dz * dz)

        target_vx = 0.0
        target_vz = 0.0
        speed = self.config.move_speed

        # ---------------- creeper fuse logic ----------------
        if self.config.explosive:
            if full_dist <= self.config.attack_range and not getattr(player, "is_dead", False):
                if self.fuse < 0.0:
                    self.fuse = 0.0
                    self._hissed = False
                self.fuse += dt
                if not self._hissed:
                    self._hissed = True
                    play_game_sound("hiss", settings)
                # flash white & swell while hissing
                try:
                    from ursina import color
                    f = 0.5 + 0.5 * math.sin(self.fuse * 26.0)
                    c = color.rgb(1.0, 0.55 + 0.45 * f, 0.55 + 0.45 * f)
                    for p in self.part_entities:
                        p.color = c
                    s = 1.0 + 0.12 * (self.fuse / 1.6)
                    self.root_entity.scale = (s, s, s)
                except Exception:
                    pass
                if self.fuse >= 1.6:
                    self._explode(player, settings)
                    return
            else:
                if self.fuse >= 0.0:
                    self.fuse = -1.0
                    self._set_flash_color(False)
                    try:
                        self.root_entity.scale = (1, 1, 1)
                    except Exception:
                        pass

        if self.hostile and self.world.difficulty != "Peaceful" and not getattr(player, "is_dead", False):
            if full_dist <= self.config.detect_range and horiz_dist > 0.05:
                dir_x = dx / horiz_dist
                dir_z = dz / horiz_dist
                self.yaw = math.degrees(math.atan2(dir_x, dir_z))
                stop_range = self.config.attack_range * 0.8 if self.config.explosive else max(1.1, self.config.attack_range * 0.75)
                if horiz_dist > stop_range:
                    target_vx = dir_x * speed
                    target_vz = dir_z * speed
                if not self.config.explosive and full_dist <= self.config.attack_range and self.attack_timer <= 0.0:
                    self.attack_timer = self.config.attack_cooldown
                    mult = DIFFICULTY_DAMAGE_MULTIPLIER.get(self.world.difficulty, 1.0)
                    dmg = self.config.attack_damage * mult
                    if dmg > 0.0:
                        player.take_damage(dmg, source=self.name, knockback_dir=(dir_x, dir_z), settings=settings)
            else:
                target_vx, target_vz = self._update_wander(dt, speed * 0.55)
        else:
            if self.flee_timer > 0.0:
                self.flee_timer -= dt
                target_vx = self.wander_dir[0] * speed * 1.45
                target_vz = self.wander_dir[1] * speed * 1.45
                if abs(target_vx) + abs(target_vz) > 0.05:
                    self.yaw = math.degrees(math.atan2(target_vx, target_vz))
            else:
                target_vx, target_vz = self._update_wander(dt, speed * 0.65)

        decay = min(1.0, dt * 8.0)
        self.vx = self.vx * (1.0 - decay) + target_vx * decay
        self.vz = self.vz * (1.0 - decay) + target_vz * decay

        # Gravity & buoyancy
        bx, by, bz = math.floor(self.x), math.floor(self.y), math.floor(self.z)
        if self.world.is_water(bx, by, bz):
            self.vy = min(2.5, self.vy + 12.0 * dt)
        else:
            self.vy = max(-24.0, self.vy - 22.0 * dt)

        new_y = self.y + self.vy * dt
        floor_y = math.floor(new_y)
        if self.vy <= 0.0 and self.world.is_solid(bx, floor_y, bz):
            self.y = float(floor_y + 1)
            self.vy = 0.0
            on_ground = True
        else:
            self.y = max(1.0, new_y)
            on_ground = False

        nx = self.x + self.vx * dt
        nz = self.z + self.vz * dt
        foot_y = math.floor(self.y + 0.05)
        if not self.world.is_solid(math.floor(nx), foot_y, math.floor(self.z)) and not self.world.is_solid(math.floor(nx), foot_y + 1, math.floor(self.z)):
            self.x = nx
        elif on_ground and not self.world.is_solid(math.floor(nx), foot_y + 1, math.floor(self.z)) and not self.world.is_solid(math.floor(nx), foot_y + 2, math.floor(self.z)):
            self.vy = 6.8
        if not self.world.is_solid(math.floor(self.x), foot_y, math.floor(nz)) and not self.world.is_solid(math.floor(self.x), foot_y + 1, math.floor(nz)):
            self.z = nz
        elif on_ground and not self.world.is_solid(math.floor(self.x), foot_y + 1, math.floor(nz)) and not self.world.is_solid(math.floor(self.x), foot_y + 2, math.floor(nz)):
            self.vy = 6.8

        move_mag = math.sqrt(self.vx * self.vx + self.vz * self.vz)
        self._animate_limbs(move_mag, dt)
        self._sync_visuals()

    def _explode(self, player, settings=None) -> None:
        """Creeper detonation: crater + radial player damage."""
        self.dead = True
        px, py, pz = player.position
        dist = math.sqrt((px - self.x) ** 2 + (py - self.y) ** 2 + (pz - self.z) ** 2)
        if hasattr(self.world, "explode"):
            self.world.explode((self.x, self.y + 0.6, self.z), radius=2.4, settings=settings)
        if dist < 6.0 and not getattr(player, "is_dead", False):
            dmg = max(0.0, 14.0 * (1.0 - dist / 6.0))
            dir_x = (px - self.x) / max(0.001, dist)
            dir_z = (pz - self.z) / max(0.001, dist)
            player.take_damage(dmg, source="Creeper", knockback_dir=(dir_x, dir_z), settings=settings)
        self.destroy_visuals()

    def _update_wander(self, dt: float, speed: float) -> Tuple[float, float]:
        self.wander_timer -= dt
        if self.wander_timer <= 0.0:
            self.wander_timer = random.uniform(2.0, 4.5)
            if random.random() < 0.45:
                self.wander_dir = (0.0, 0.0)
            else:
                ang = random.uniform(0.0, 2.0 * math.pi)
                self.wander_dir = (math.sin(ang), math.cos(ang))
                self.yaw = math.degrees(ang)
        return (self.wander_dir[0] * speed, self.wander_dir[1] * speed)


class MobManager:
    """Manages active mobs in the world, spawning, despawning, and updates."""

    MAX_MOBS = 12
    DESPAWN_DISTANCE = 46.0

    def __init__(self, world):
        self.world = world
        self.mobs: List[Mob] = []
        self.spawn_timer: float = 2.0

    def spawn_mob(self, mob_type: str, position: Tuple[float, float, float]) -> Mob:
        mob = Mob(mob_type=mob_type, position=position, world=self.world)
        self.mobs.append(mob)
        return mob

    def spawn_initial_mobs(self, player_pos: Tuple[float, float, float]) -> None:
        px, _, pz = player_pos
        initial_types = ["pig", "cow", "sheep", "pig"]
        if self.world.difficulty != "Peaceful":
            initial_types.extend(["zombie", "skeleton", "creeper"])
        for idx, mtype in enumerate(initial_types):
            ang = (idx / len(initial_types)) * 2.0 * math.pi + 0.4
            dist = 9.0 if not MOB_CONFIGS[mtype].hostile else 15.0
            sx = int(round(px + math.cos(ang) * dist))
            sz = int(round(pz + math.sin(ang) * dist))
            pos = self._find_surface_pos(sx, sz)
            if pos is not None:
                self.spawn_mob(mtype, pos)

    def _find_surface_pos(self, wx: int, wz: int) -> Optional[Tuple[float, float, float]]:
        _, sy = self.world.terrain.get_biome_and_height(wx, wz)
        if sy <= SEA_LEVEL:
            return None
        for y in range(CHUNK_HEIGHT - 2, 1, -1):
            if self.world.is_solid(wx, y, wz):
                return (float(wx) + 0.5, float(y) + 1.02, float(wz) + 0.5)
        return (float(wx) + 0.5, float(sy) + 1.02, float(wz) + 0.5)

    def update(self, dt: float, player, settings=None) -> None:
        dt = min(0.1, max(0.0, float(dt)))
        px, py, pz = player.position

        if self.world.difficulty == "Peaceful":
            for m in self.mobs:
                if m.hostile and not m.dead:
                    m.destroy_visuals()
                    m.dead = True

        alive: List[Mob] = []
        for mob in self.mobs:
            if mob.dead:
                mob.destroy_visuals()
                continue
            dx = mob.x - px
            dz = mob.z - pz
            if dx * dx + dz * dz > self.DESPAWN_DISTANCE ** 2:
                mob.destroy_visuals()
                continue
            mob.update(dt, player, settings=settings)
            if not mob.dead:
                alive.append(mob)
        self.mobs = alive

        self.spawn_timer -= dt
        if self.spawn_timer <= 0.0:
            self.spawn_timer = 4.0 if self.world.is_night else 6.5
            if len(self.mobs) < self.MAX_MOBS:
                ang = random.uniform(0.0, 2.0 * math.pi)
                dist = random.uniform(12.0, 24.0)
                sx = int(round(px + math.cos(ang) * dist))
                sz = int(round(pz + math.sin(ang) * dist))
                pos = self._find_surface_pos(sx, sz)
                if pos is not None:
                    if self.world.difficulty == "Peaceful":
                        mtype = random.choice(["pig", "cow", "sheep"])
                    elif self.world.is_night:
                        mtype = random.choice(["zombie", "skeleton", "creeper", "zombie", "creeper"])
                    else:
                        mtype = random.choice(["pig", "cow", "sheep", "pig", "cow", "zombie", "skeleton", "creeper"])
                    self.spawn_mob(mtype, pos)

    def cleanup(self) -> None:
        for mob in self.mobs:
            mob.destroy_visuals()
        self.mobs.clear()
