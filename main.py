from __future__ import division
import sys, math, random, time
from collections import deque

import pyglet
from pyglet import image
from pyglet.gl import *
from pyglet.graphics import TextureGroup
from pyglet.window import key, mouse

# === Constants and Helper Functions ========================================

TICKS_PER_SEC = 60
SECTOR_SIZE = 16
WALKING_SPEED = 5
GRAVITY = 20.0
MAX_JUMP_HEIGHT = 1.0 
JUMP_SPEED = math.sqrt(2 * GRAVITY * MAX_JUMP_HEIGHT)
TERMINAL_VELOCITY = 50
PLAYER_HEIGHT = 2

if sys.version_info[0] >= 3:
    xrange = range

def cube_vertices(x, y, z, n):
    return [
        x-n, y+n, z-n,  x-n, y+n, z+n,  x+n, y+n, z+n,  x+n, y+n, z-n,  # top
        x-n, y-n, z-n,  x+n, y-n, z-n,  x+n, y-n, z+n,  x-n, y-n, z+n,  # bottom
        x-n, y-n, z-n,  x-n, y-n, z+n,  x-n, y+n, z+n,  x-n, y+n, z-n,  # left
        x+n, y-n, z+n,  x+n, y-n, z-n,  x+n, y+n, z-n,  x+n, y+n, z+n,  # right
        x-n, y-n, z+n,  x+n, y-n, z+n,  x+n, y+n, z+n,  x-n, y+n, z+n,  # front
        x+n, y-n, z-n,  x-n, y-n, z-n,  x-n, y+n, z-n,  x+n, y+n, z-n,  # back
    ]

def tex_coord(x, y, n=4):
    m = 1.0 / n
    dx = x * m
    dy = y * m
    return dx, dy, dx + m, dy, dx + m, dy + m, dx, dy + m

def tex_coords(top, bottom, side):
    top = tex_coord(*top)
    bottom = tex_coord(*bottom)
    side = tex_coord(*side)
    result = []
    result.extend(top)
    result.extend(bottom)
    result.extend(side * 4)
    return result

# === Texture Definitions =====================================================

TEXTURE_PATH = 'texture.png'
GRASS = tex_coords((1, 0), (0, 1), (0, 0))
SAND  = tex_coords((1, 1), (1, 1), (1, 1))
BRICK = tex_coords((2, 0), (2, 0), (2, 0))
STONE = tex_coords((2, 1), (2, 1), (2, 1))

FACES = [
    ( 0, 1, 0),
    ( 0,-1, 0),
    (-1, 0, 0),
    ( 1, 0, 0),
    ( 0, 0, 1),
    ( 0, 0,-1),
]

def normalize(position):
    x, y, z = position
    return (int(round(x)), int(round(y)), int(round(z)))

def sectorize(position):
    x, y, z = normalize(position)
    return (x // SECTOR_SIZE, 0, z // SECTOR_SIZE)

# === Model: World and Static Blocks ==========================================

class Model(object):
    def __init__(self):
        self.batch = pyglet.graphics.Batch()
        self.group = TextureGroup(image.load(TEXTURE_PATH).get_texture())
        self.world = {}
        self.shown = {}
        self._shown = {}
        self.sectors = {}
        self.queue = deque()
        self._initialize()

    def _initialize(self):
        n = 80  
        s = 1  
        y = 0  
        for x in xrange(-n, n + 1, s):
            for z in xrange(-n, n + 1, s):
                self.add_block((x, y - 2, z), GRASS, immediate=False)
                self.add_block((x, y - 3, z), STONE, immediate=False)
                if x in (-n, n) or z in (-n, n):
                    for dy in xrange(-2, 3):
                        self.add_block((x, y + dy, z), STONE, immediate=False)

    def add_block(self, position, texture, immediate=True):
        self.world[position] = texture
        sector = sectorize(position)
        self.sectors.setdefault(sector, []).append(position)
        if self.exposed(position):
            self.show_block(position, immediate)

    def hit_test(self, position, vector, max_distance=8):
        m = 8
        x, y, z = position
        dx, dy, dz = vector
        previous = None
        for _ in xrange(max_distance * m):
            key = normalize((x, y, z))
            if key != previous and key in self.world:
                return key, previous
            previous = key
            x, y, z = x + dx / m, y + dy / m, z + dz / m
        return None, None

    def exposed(self, position):
        x, y, z = position
        for dx, dy, dz in FACES:
            if (x + dx, y + dy, z + dz) not in self.world:
                return True
        return False

    def show_block(self, position, immediate=True):
        texture = self.world[position]
        self.shown[position] = texture
        if immediate:
            self._show_block(position, texture)
        else:
            self._enqueue(self._show_block, position, texture)

    def _show_block(self, position, texture):
        x, y, z = position
        vertex_data = cube_vertices(x, y, z, 0.5)
        texture_data = list(texture)
        self._shown[position] = self.batch.add(24, GL_QUADS, self.group,
            ('v3f/static', vertex_data),
            ('t2f/static', texture_data))

    def hide_block(self, position, immediate=True):
        self.shown.pop(position)
        if immediate:
            self._hide_block(position)
        else:
            self._enqueue(self._hide_block, position)

    def _hide_block(self, position):
        self._shown.pop(position).delete()

    def show_sector(self, sector):
        for position in self.sectors.get(sector, []):
            if position not in self.shown and self.exposed(position):
                self.show_block(position, False)

    def hide_sector(self, sector):
        for position in self.sectors.get(sector, []):
            if position in self.shown:
                self.hide_block(position, False)

    def change_sectors(self, before, after):
        before_set = set()
        after_set = set()
        pad = 4
        for dx in xrange(-pad, pad + 1):
            for dy in [0]:
                for dz in xrange(-pad, pad + 1):
                    if dx ** 2 + dy ** 2 + dz ** 2 > (pad + 1) ** 2:
                        continue
                    if before:
                        bx, by, bz = before
                        before_set.add((bx + dx, by + dy, bz + dz))
                    if after:
                        ax, ay, az = after
                        after_set.add((ax + dx, ay + dy, az + dz))
        show = after_set - before_set
        hide = before_set - after_set
        for sector in show:
            self.show_sector(sector)
        for sector in hide:
            self.hide_sector(sector)

    def _enqueue(self, func, *args):
        self.queue.append((func, args))

    def _dequeue(self):
        func, args = self.queue.popleft()
        func(*args)

    def process_queue(self):
        start = time.perf_counter()
        while self.queue and time.perf_counter() - start < 1.0 / TICKS_PER_SEC:
            self._dequeue()

    def process_entire_queue(self):
        while self.queue:
            self._dequeue()

# === Dynamic Entities: Bullets and Enemies ===================================

class Bullet(object):
    """A bullet is a small moving cube that damages whoever it hits.
       owner is either "player" or an Enemy instance."""
    def __init__(self, position, direction, speed, owner, lifetime=3.0):
        self.position = position
        length = math.sqrt(direction[0]**2 + direction[1]**2 + direction[2]**2)
        self.direction = (direction[0]/length, direction[1]/length, direction[2]/length)
        self.speed = speed
        self.owner = owner
        self.size = 0.1
        self.lifetime = lifetime
        self.age = 0

    def update(self, dt):
        self.position = (self.position[0] + self.direction[0]*self.speed*dt,
                         self.position[1] + self.direction[1]*self.speed*dt,
                         self.position[2] + self.direction[2]*self.speed*dt)
        self.age += dt

    def draw(self):
        glColor3f(1.0, 0.0, 0.0)
        vertices = cube_vertices(*self.position, self.size)
        pyglet.graphics.draw(24, GL_QUADS, ('v3f/static', vertices))

class Enemy(object):
    """A simple enemy made of two blocks (each 1 block tall) with a hitbox
       roughly 1×2 blocks and health. It uses the provided speed and shooting rate."""
    def __init__(self, position, speed=2.0, shoot_interval=2.0):
        self.position = position 
        self.health = 100
        self.speed = speed
        self.shoot_interval = shoot_interval
        self.time_since_shot = 0.0

    def update(self, dt, player_position, bullet_list):
        
        ex, ey, ez = self.position
        px, py, pz = player_position
        dx = px - ex
        dz = pz - ez
        dist = math.sqrt(dx*dx + dz*dz)
        if dist > 0:
            dx /= dist
            dz /= dist
        ex += dx * self.speed * dt
        ez += dz * self.speed * dt
        self.position = (ex, ey, ez)
        
        self.time_since_shot += dt
        if self.time_since_shot >= self.shoot_interval:
            self.time_since_shot = 0.0
            aim_from = (ex, ey + 1, ez)  
            direction = (px - aim_from[0], py - aim_from[1], pz - aim_from[2])
            bullet = Bullet(aim_from, direction, speed=20, owner=self)
            bullet_list.append(bullet)

    def draw(self):
        glColor3f(0.6, 0.3, 0.0) 
        x, y, z = self.position
        vertices_lower = cube_vertices(x, y, z, 0.5)
        pyglet.graphics.draw(24, GL_QUADS, ('v3f/static', vertices_lower))
        vertices_upper = cube_vertices(x, y + 1, z, 0.5)
        pyglet.graphics.draw(24, GL_QUADS, ('v3f/static', vertices_upper))
        
    def get_aabb(self):
        x, y, z = self.position
        return (x - 0.5, y, z - 0.5, x + 0.5, y + 2, z + 0.5)

def point_in_aabb(point, aabb):
    x, y, z = point
    minx, miny, minz, maxx, maxy, maxz = aabb
    return (minx <= x <= maxx and miny <= y <= maxy and minz <= z <= maxz)

# === Enemy Spawner ===========================================================


class EnemySpawner(object):
    def __init__(self, center, width, depth, count,
                 respawn_time_range, speed_range, shoot_rate_range,
                 spawn_y=-1):
        """
        center: tuple (center_x, center_z) for the spawn area.
        width, depth: dimensions of the area.
        count: maximum number of active enemies from this spawner.
        respawn_time_range: (min, max) seconds between spawns.
        speed_range: (min, max) enemy speed.
        shoot_rate_range: (min, max) enemy shoot interval.
        spawn_y: the y-coordinate for spawning (so enemies are on the ground).
        """
        self.center = center
        self.width = width
        self.depth = depth
        self.count = count
        self.respawn_time_range = respawn_time_range
        self.speed_range = speed_range
        self.shoot_rate_range = shoot_rate_range
        self.spawn_y = spawn_y
        self.time_until_next_spawn = random.uniform(*respawn_time_range)

    def update(self, dt, enemy_list):
        active_count = len(enemy_list)
        self.time_until_next_spawn -= dt
        if self.time_until_next_spawn <= 0 and active_count < self.count:
            spawn_x = random.uniform(self.center[0] - self.width/2,
                                     self.center[0] + self.width/2)
            spawn_z = random.uniform(self.center[1] - self.depth/2,
                                     self.center[1] + self.depth/2)
            spawn_position = (spawn_x, self.spawn_y, spawn_z)
            speed = random.uniform(self.speed_range[0], self.speed_range[1])
            shoot_interval = random.uniform(self.shoot_rate_range[0], self.shoot_rate_range[1])
            enemy = Enemy(spawn_position, speed=speed, shoot_interval=shoot_interval)
            enemy_list.append(enemy)
            self.time_until_next_spawn = random.uniform(*self.respawn_time_range)

# === Window and Main Game Loop ===============================================

class Window(pyglet.window.Window):
    def __init__(self, *args, **kwargs):
        super(Window, self).__init__(*args, **kwargs)
        self.exclusive = False
        self.strafe = [0, 0]
        self.position = (0, 1.5, 5) 
        self.rotation = (0, 0)
        self.sector = None
        self.reticle = None
        self.dy = 0
        self.inventory = [BRICK, GRASS, SAND]
        self.block = self.inventory[0]
        self.num_keys = [key._1, key._2, key._3, key._4, key._5,
                         key._6, key._7, key._8, key._9, key._0]
        self.model = Model()
        self.label = pyglet.text.Label('', font_name='Arial', font_size=18,
                                       x=10, y=self.height - 10,
                                       anchor_x='left', anchor_y='top',
                                       color=(0, 0, 0, 255))
        pyglet.clock.schedule_interval(self.update, 1.0 / TICKS_PER_SEC)
        
        self.player_health = 100
        self.enemies = []
        self.bullets = []
        self.enemy_spawner = EnemySpawner(center=(0, -10),
                                          width=30, depth=30, count=5,
                                          respawn_time_range=(2, 6),
                                          speed_range=(1.5, 5.0),
                                          shoot_rate_range=(1.0, 3.0),
                                          spawn_y=-1)

    def set_exclusive_mouse(self, exclusive):
        super(Window, self).set_exclusive_mouse(exclusive)
        self.exclusive = exclusive

    def get_sight_vector(self):
        x, y = self.rotation
        m = math.cos(math.radians(y))
        dy = math.sin(math.radians(y))
        dx = math.cos(math.radians(x - 90)) * m
        dz = math.sin(math.radians(x - 90)) * m
        return (dx, dy, dz)

    def get_motion_vector(self):
        if any(self.strafe):
            x, y = self.rotation
            strafe = math.degrees(math.atan2(*self.strafe))
            x_angle = math.radians(x + strafe)
            dx = math.cos(x_angle)
            dz = math.sin(x_angle)
        else:
            dx = 0.0
            dz = 0.0
        return (dx, 0.0, dz)

    def update(self, dt):
        self.model.process_queue()
        sector = sectorize(self.position)
        if sector != self.sector:
            self.model.change_sectors(self.sector, sector)
            if self.sector is None:
                self.model.process_entire_queue()
            self.sector = sector

        m = 8
        dt = min(dt, 0.2)
        for _ in xrange(m):
            self._update(dt / m)


        for bullet in self.bullets[:]:
            bullet.update(dt)
            if bullet.age > bullet.lifetime:
                self.bullets.remove(bullet)
                continue
            if bullet.owner == "player":
                for enemy in self.enemies:
                    if point_in_aabb(bullet.position, enemy.get_aabb()):
                        enemy.health -= 20
                        self.bullets.remove(bullet)
                        print("Enemy hit! Health now:", enemy.health)
                        break
            else:
                px, py, pz = self.position
                player_aabb = (px - 0.5, py, pz - 0.5, px + 0.5, py + PLAYER_HEIGHT, pz + 0.5)
                if point_in_aabb(bullet.position, player_aabb):
                    self.player_health -= 10
                    self.bullets.remove(bullet)
                    print("Player hit! Health now:", self.player_health)
                    break

        for enemy in self.enemies[:]:
            enemy.update(dt, self.position, self.bullets)
            if enemy.health <= 0:
                print("Enemy defeated!")
                self.enemies.remove(enemy)

        self.enemy_spawner.update(dt, self.enemies)

    def _update(self, dt):
        speed = WALKING_SPEED
        d = dt * speed
        dx, dy, dz = self.get_motion_vector()
        dx, dy, dz = dx * d, dy * d, dz * d
        self.dy -= dt * GRAVITY
        self.dy = max(self.dy, -TERMINAL_VELOCITY)
        dy += self.dy * dt
        x, y, z = self.position
        x, y, z = self.collide((x + dx, y + dy, z + dz), PLAYER_HEIGHT)
        self.position = (x, y, z)

    def collide(self, position, height):
        pad = 0.25
        p = list(position)
        np_pos = normalize(position)
        for face in FACES:
            for i in xrange(3):
                if not face[i]:
                    continue
                d = (p[i] - np_pos[i]) * face[i]
                if d < pad:
                    continue
                for dy in xrange(height):
                    op = list(np_pos)
                    op[1] -= dy
                    op[i] += face[i]
                    if tuple(op) not in self.model.world:
                        continue
                    p[i] -= (d - pad) * face[i]
                    if face in [(0, -1, 0), (0, 1, 0)]:
                        self.dy = 0
                    break
        return tuple(p)

    def on_mouse_press(self, x, y, button, modifiers):
        if self.exclusive:
            if button == mouse.LEFT:
                self.shoot_bullet("player")
        else:
            self.set_exclusive_mouse(True)

    def shoot_bullet(self, owner):
        if owner == "player":
            sight = self.get_sight_vector()
            pos = (self.position[0] + sight[0] * 0.5,
                   self.position[1] + sight[1] * 0.5,
                   self.position[2] + sight[2] * 0.5)
            bullet = Bullet(pos, sight, speed=30, owner="player")
            self.bullets.append(bullet)

    def on_mouse_motion(self, x, y, dx, dy):
        if self.exclusive:
            m = 0.15
            rx, ry = self.rotation
            rx, ry = rx + dx * m, ry + dy * m
            ry = max(-90, min(90, ry))
            self.rotation = (rx, ry)

    def on_key_press(self, symbol, modifiers):
        if symbol == key.W:
            self.strafe[0] -= 1
        elif symbol == key.S:
            self.strafe[0] += 1
        elif symbol == key.A:
            self.strafe[1] -= 1
        elif symbol == key.D:
            self.strafe[1] += 1
        elif symbol == key.SPACE:
            if self.dy == 0:
                self.dy = JUMP_SPEED
        elif symbol == key.ESCAPE:
            self.set_exclusive_mouse(False)
        elif symbol in self.num_keys:
            index = (symbol - self.num_keys[0]) % len(self.inventory)
            self.block = self.inventory[index]

    def on_key_release(self, symbol, modifiers):
        if symbol == key.W:
            self.strafe[0] += 1
        elif symbol == key.S:
            self.strafe[0] -= 1
        elif symbol == key.A:
            self.strafe[1] += 1
        elif symbol == key.D:
            self.strafe[1] -= 1

    def on_resize(self, width, height):
        self.label.y = height - 10
        if self.reticle:
            self.reticle.delete()
        x, y = self.width // 2, self.height // 2
        n = 10
        self.reticle = pyglet.graphics.vertex_list(4,
            ('v2i', (x - n, y, x + n, y, x, y - n, x, y + n))
        )

    def set_2d(self):
        width, height = self.get_size()
        glDisable(GL_DEPTH_TEST)
        glViewport(0, 0, max(1, width), max(1, height))
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        glOrtho(0, width, 0, height, -1, 1)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()

    def set_3d(self):
        width, height = self.get_size()
        glEnable(GL_DEPTH_TEST)
        glViewport(0, 0, max(1, width), max(1, height))
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(65.0, width / float(height), 0.1, 60.0)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        rx, ry = self.rotation
        glRotatef(rx, 0, 1, 0)
        glRotatef(-ry, math.cos(math.radians(rx)), 0, math.sin(math.radians(rx)))
        x, y, z = self.position
        glTranslatef(-x, -y, -z)

    def on_draw(self):
        self.clear()
        self.set_3d()
        glColor3f(1, 1, 1)
        self.model.batch.draw()

        # Draw an outline around the block you're aiming at.
        self.draw_focused_block()

        # Draw enemies.
        for enemy in self.enemies:
            enemy.draw()

        # Draw bullets.
        for bullet in self.bullets:
            bullet.draw()

        self.set_2d()
        self.draw_label()
        self.draw_reticle()

    def draw_focused_block(self):
        vector = self.get_sight_vector()
        block = self.model.hit_test(self.position, vector)[0]
        if block:
            x, y, z = block
            vertex_data = cube_vertices(x, y, z, 0.51)
            glColor3d(0, 0, 0)
            glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
            pyglet.graphics.draw(24, GL_QUADS, ('v3f/static', vertex_data))
            glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)

    def draw_label(self):
        x, y, z = self.position
        self.label.text = 'Pos: (%.2f, %.2f, %.2f) | Health: %d | Enemies: %d' % (
            x, y, z, self.player_health, len(self.enemies))
        self.label.draw()

    def draw_reticle(self):
        glColor3f(0, 0, 0)
        self.reticle.draw(GL_LINES)

# === OpenGL Setup Functions ================================================

def setup_fog():
    glEnable(GL_FOG)
    fogColor = (GLfloat * 4)(0.5, 0.69, 1.0, 1)
    glFogfv(GL_FOG_COLOR, fogColor)
    glHint(GL_FOG_HINT, GL_DONT_CARE)
    glFogi(GL_FOG_MODE, GL_LINEAR)
    glFogf(GL_FOG_START, 20.0)
    glFogf(GL_FOG_END, 60.0)

def setup():
    glClearColor(0.5, 0.69, 1.0, 1)
    glEnable(GL_CULL_FACE)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
    setup_fog()

# === Main Entry Point =======================================================

def main():
    window = Window(width=800, height=600, caption='FPS Prototype with Spawner', resizable=True)
    window.set_exclusive_mouse(True)
    setup()
    pyglet.app.run()

if __name__ == '__main__':
    main()
