"""Minimal semantic LiDAR map recorder for CARLA.

Features:
 - Spawn ego vehicle & semantic LiDAR
 - Smooth simple keyboard control (W/S throttle+brake, A/D steer, Space full brake, Q reverse toggle)
 - Dynamic objects filtered out for static map
 - Optional voxel downsampling
 - PCD export (ascii/binary) + optional center + YAML for Autoware

Intentionally minimal: one set of baked-in smoothing values, no tuning flags clutter.
"""

import argparse
import os
import time
import numpy as np
import queue

try:
    import open3d as o3d  # type: ignore
except Exception:
    o3d = None

try:
    import pygame  # type: ignore
except Exception:
    pygame = None

import carla  # type: ignore


def parse_args():
    p = argparse.ArgumentParser(description='Minimal CARLA semantic LiDAR recorder')
    p.add_argument('--host', default='localhost')
    p.add_argument('--port', type=int, default=2000)
    p.add_argument('--town', default='Town05')
    p.add_argument('--out', default='pointcloud_map.pcd', help='Output PCD filename (Autoware default: pointcloud_map.pcd)')
    p.add_argument('--voxel', type=float, default=0.08, help='Voxel size (meters) for downsampling (0 to disable)')
    p.add_argument('--duration', type=float, default=0.0, help='Optional max capture duration seconds (0 = unlimited)')
    p.add_argument('--channels', type=int, default=64)
    p.add_argument('--rotation-freq', type=float, default=10.0)
    p.add_argument('--pps', type=int, default=2_000_000)
    p.add_argument('--range', type=float, default=100.0)
    p.add_argument('--upper-fov', type=float, default=10.0)
    p.add_argument('--lower-fov', type=float, default=-30.0)
    p.add_argument('--pcd-format', choices=['ascii', 'binary'], default='binary')
    p.add_argument('--center-origin', action='store_true', help='Translate cloud so XY mean becomes (0,0) (helpful for Autoware localization)')
    p.add_argument('--write-yaml', action='store_true', help='Write simple pointcloud_map.yaml metadata file')
    p.add_argument('--height', type=float, default=2.2, help='LiDAR mount height (meters)')
    p.add_argument('--follow-spectator', action='store_true', default=True, help='Continuously position spectator to follow ego vehicle')
    p.add_argument('--max-kmh', type=float, default=30.0, help='Approximate max speed (km/h). Throttle feathered above this.')
    return p.parse_args()


def dynamic_label_ids(label_enum) -> set:
    names = ['Pedestrians', 'Rider', 'Vehicles', 'AnimatedCharacters', 'Bicycles', 'Motorcycles']
    out = set()
    for n in names:
        if hasattr(label_enum, n):
            out.add(int(getattr(label_enum, n)))
    return out


def rotation_matrix(roll, pitch, yaw):
    import math
    r = math.radians(roll); p = math.radians(pitch); y = math.radians(yaw)
    cr, sr = math.cos(r), math.sin(r)
    cp, sp = math.cos(p), math.sin(p)
    cy, sy = math.cos(y), math.sin(y)
    Rz = np.array([[cy, -sy, 0],[sy, cy, 0],[0,0,1]], dtype=np.float64)
    Ry = np.array([[cp,0,sp],[0,1,0],[-sp,0,cp]], dtype=np.float64)
    Rx = np.array([[1,0,0],[0,cr,-sr],[0,sr,cr]], dtype=np.float64)
    return Rz @ Ry @ Rx


def transform_points(points, transform: carla.Transform):
    loc = transform.location; rot = transform.rotation
    R = rotation_matrix(rot.roll, rot.pitch, rot.yaw)
    t = np.array([[loc.x],[loc.y],[loc.z]], dtype=np.float64)
    return (R @ points.T + t).T


def world_to_enu(points):
    pts = points.copy(); pts[:,1] *= -1.0; return pts


class MiniKeyboardControl:
    """Minimal keyboard control (Option B) using core CARLA example key semantics.

    Keys:
      W / Up     : throttle (ramped)
      S / Down   : brake (or light reverse when held in reverse mode)
      A / Left   : steer left (ramped)
      D / Right  : steer right (ramped)
      SPACE      : full brake
      Q          : toggle reverse
      ESC / Close window: quit
    """
    def __init__(self, vehicle):
        self.vehicle = vehicle
        self.quit = False
        self.reverse = False
        self._throttle = 0.0  # forward throttle ramp (also used for reverse when reverse flag set)
        self._steer_cache = 0.0
        self._last_time = time.time()
        self.max_kmh = 30.0  # default, may be overridden externally
        self._speed_kmh = 0.0
        # Fixed smooth control parameters (kept intentionally simple)
        self._ACCEL_RATE = 1.15        # throttle ramp up /s
        self._DECEL_RATE = 1.6         # throttle decay /s
        self._STEER_RATE = 3.2         # steer change toward target /s
        self._STEER_RETURN = 4.5       # steer recenter /s
        self._BRAKE_S = 0.55           # service brake (S key)
        self._BRAKE_SPACE = 1.0        # full brake (Space)
        self._STEER_ATTEN_SCALE = 40.0 # higher => gentler attenuation
        if pygame is not None:
            try:
                pygame.init()
                self.surface = pygame.display.set_mode((520,110))
                pygame.display.set_caption('CARLA Mini Keyboard Control (WASD, Space brake, Q reverse, ESC quit)')
                self.clock = pygame.time.Clock()
                self.font = pygame.font.SysFont('Arial',16)
            except Exception:
                self.surface = None
                self.clock = None
                self.font = None
        else:
            self.surface = None
            self.clock = None
            self.font = None

    def _apply_vehicle_control(self, throttle, steer, brake):
        ctrl = carla.VehicleControl()
        ctrl.throttle = float(np.clip(throttle, 0.0, 1.0))
        ctrl.steer = float(np.clip(steer, -1.0, 1.0))
        ctrl.brake = float(np.clip(brake, 0.0, 1.0))
        ctrl.reverse = self.reverse
        try:
            self.vehicle.apply_control(ctrl)
        except RuntimeError:
            pass
        return ctrl

    def tick(self):
        if pygame is None:
            return True
        now = time.time()
        dt = max(1e-3, now - self._last_time)
        self._last_time = now
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.quit = True
            elif event.type == pygame.KEYDOWN:
                mods = pygame.key.get_mods()
                if event.key == pygame.K_ESCAPE:
                    self.quit = True
                elif event.key == pygame.K_q and (mods & pygame.KMOD_CTRL):  # Ctrl+Q quit
                    self.quit = True
                elif event.key == pygame.K_q:  # plain Q toggles reverse only
                    self.reverse = not self.reverse
        keys = pygame.key.get_pressed()
        # Update current speed (km/h)
        try:
            v = self.vehicle.get_velocity()
            self._speed_kmh = 3.6 * (v.x*v.x + v.y*v.y + v.z*v.z) ** 0.5
        except Exception:
            self._speed_kmh = 0.0

        # Throttle ramp (single pedal behavior; Q toggles reverse) with tunable rates
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            self._throttle += self._ACCEL_RATE * dt
        else:
            self._throttle -= self._DECEL_RATE * dt
        self._throttle = float(np.clip(self._throttle, 0.0, 1.0))

        # Speed limiting (soft feather above 95%, hard cut above max)
        if self._speed_kmh > self.max_kmh:
            eff_throttle = 0.0
        elif self._speed_kmh > 0.95 * self.max_kmh:
            eff_throttle = self._throttle * 0.3
        else:
            eff_throttle = self._throttle

        # Steering target from keys (-1,0,1)
        steer_target = 0.0
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            steer_target = -1.0
        elif keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            steer_target = 1.0
        # Speed-based attenuation (simple: divide by (1 + v/scale))
        atten = 1.0 / (1.0 + self._speed_kmh / self._STEER_ATTEN_SCALE)
        steer_target *= atten
        # Smooth ramp toward target
        diff = steer_target - self._steer_cache
        max_step = self._STEER_RATE * dt
        if diff > max_step:
            diff = max_step
        elif diff < -max_step:
            diff = -max_step
        self._steer_cache += diff
        if abs(steer_target) < 1e-3:  # recenter when no input
            self._steer_cache *= max(0.0, 1.0 - self._STEER_RETURN * dt)
        self._steer_cache = float(np.clip(self._steer_cache, -1.0, 1.0))

        brake = 0.0
        if keys[pygame.K_SPACE]:
            brake = self._BRAKE_SPACE
            eff_throttle = 0.0
        elif keys[pygame.K_s] or keys[pygame.K_DOWN]:
            brake = self._BRAKE_S

        ctrl = self._apply_vehicle_control(eff_throttle, self._steer_cache, brake)

        if self.clock:
            self.clock.tick_busy_loop(60)
            if self.surface and self.font:
                self.surface.fill((25,25,25))
                txt1 = f'Spd {self._speed_kmh:5.1f} km/h  Thr {ctrl.throttle:.2f} Steer {ctrl.steer:.2f} Brk {ctrl.brake:.2f} Rev {ctrl.reverse}'
                self.surface.blit(self.font.render(txt1, True, (230,230,230)), (8,8))
                self.surface.blit(self.font.render(f'Max {self.max_kmh:.0f} km/h | Q reverse | ESC/Ctrl+Q quit', True, (150,150,150)), (8,34))
                pygame.display.flip()
        return not self.quit

    def close(self):
        if pygame is not None:
            try:
                pygame.quit()
            except Exception:
                pass


def main():
    args = parse_args()
    if o3d is None:
        raise RuntimeError('open3d not installed: pip install open3d')

    client = carla.Client(args.host, args.port)
    client.set_timeout(10.0)
    world = client.get_world()
    if world.get_map().name.split('/')[-1] != args.town:
        print(f'[INFO] Loading {args.town} ...')
        world = client.load_world(args.town)
        time.sleep(1.0)

    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.05
    world.apply_settings(settings)
    original_settings = settings

    # Vehicle spawn
    bps = world.get_blueprint_library().filter('vehicle.lincoln.mkz_2017')
    blue = np.random.choice([bp for bp in bps if bp.has_attribute('number_of_wheels') and int(bp.get_attribute('number_of_wheels').as_int())==4])
    if blue.has_attribute('role_name'): blue.set_attribute('role_name','ego')
    spawn_point = carla.Transform(
    carla.Location(x=0.0, y=1.0, z=1.0),  # <-- Replace with your desired position
    carla.Rotation(pitch=0.0, yaw=180.0, roll=0.0)
      )  # <-- Orientation
    vehicle = world.try_spawn_actor(blue, spawn_point)
    print(f'[INFO] Vehicle: {vehicle.type_id}')

    # LiDAR
    bp = world.get_blueprint_library().find('sensor.lidar.ray_cast_semantic')
    bp.set_attribute('channels', str(args.channels))
    bp.set_attribute('rotation_frequency', str(args.rotation_freq))
    bp.set_attribute('points_per_second', str(args.pps))
    bp.set_attribute('range', str(args.range))
    bp.set_attribute('upper_fov', str(args.upper_fov))
    bp.set_attribute('lower_fov', str(args.lower_fov))
    bp.set_attribute('horizontal_fov', '360')
    bp.set_attribute('sensor_tick', '0.0')
    rel = carla.Transform(carla.Location(z=args.height))
    lidar = world.spawn_actor(bp, rel, attach_to=vehicle)

    q = queue.Queue(maxsize=20)
    def _cb(meas):
        try: q.put_nowait(meas)
        except queue.Full: pass
    lidar.listen(_cb)

    # Always filter dynamic semantic labels for static map (Autoware requirement)
    dyn_ids = dynamic_label_ids(carla.CityObjectLabel)

    all_pts = []
    scans = 0
    t0 = time.time()
    teleop = MiniKeyboardControl(vehicle)
    teleop.max_kmh = args.max_kmh
    spectator = world.get_spectator() if args.follow_spectator else None
    print('[INFO] Recording... press Q in window or Ctrl+C to stop.')

    try:
        while True:
            world.tick()
            # spectator follow (simple chase cam)
            if spectator is not None:
                v_tf = vehicle.get_transform()
                yaw = v_tf.rotation.yaw
                import math
                back_dist = 8.0
                dx = back_dist * math.cos(math.radians(yaw))
                dy = back_dist * math.sin(math.radians(yaw))
                loc = v_tf.location - carla.Location(x=dx, y=dy) + carla.Location(z=4.0)
                rot = carla.Rotation(pitch=-15, yaw=yaw)
                spectator.set_transform(carla.Transform(loc, rot))
            if not teleop.tick():
                break
            # drain a few measurements
            for _ in range(4):
                try:
                    m = q.get_nowait()
                except queue.Empty:
                    break
                data = np.frombuffer(m.raw_data, dtype=np.dtype([
                    ('x', np.float32), ('y', np.float32), ('z', np.float32),
                    ('CosAngle', np.float32), ('ObjIdx', np.uint32), ('ObjTag', np.uint32)
                ]))
                pts = np.stack([data['x'], data['y'], data['z']], axis=-1).astype(np.float64)
                if dyn_ids:
                    labels = data['ObjTag'].astype(np.int32)
                    mask = ~np.isin(labels, list(dyn_ids))
                    pts = pts[mask]
                if pts.size:
                    pts_world = transform_points(pts, lidar.get_transform())
                    pts_enu = world_to_enu(pts_world)
                    all_pts.append(pts_enu)
                    scans += 1
            if args.duration > 0 and (time.time() - t0) >= args.duration:
                print('[INFO] Duration reached.')
                break
            if scans and scans % 50 == 0:
                total = sum(p.shape[0] for p in all_pts)
                print(f'  scans={scans} points~{total}')
    except KeyboardInterrupt:
        print('\n[INFO] Interrupted')
    finally:
        try:
            lidar.stop()
        except Exception:
            pass
        try:
            teleop.close()
        except Exception:
            pass
        try:
            world.apply_settings(original_settings)
        except Exception:
            pass

    if not all_pts:
        print('[WARN] No data captured.')
        return

    points = np.vstack(all_pts)
    print(f'[INFO] Raw collected points: {points.shape[0]}')
    if args.voxel > 0:
        pcd_tmp = o3d.geometry.PointCloud()
        pcd_tmp.points = o3d.utility.Vector3dVector(points)
        pcd_ds = pcd_tmp.voxel_down_sample(args.voxel)
        points = np.asarray(pcd_ds.points)
        print(f'[INFO] After voxel {args.voxel}: {points.shape[0]} points')

    if args.center_origin:
        xy_mean = points[:, :2].mean(axis=0)
        points[:, 0] -= xy_mean[0]
        points[:, 1] -= xy_mean[1]
        print(f'[INFO] Centered XY by subtracting mean ({xy_mean[0]:.2f}, {xy_mean[1]:.2f})')

    pcd = o3d.geometry.PointCloud(); pcd.points = o3d.utility.Vector3dVector(points)
    out_abs = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_abs), exist_ok=True)
    write_ascii = (args.pcd_format == 'ascii')
    ok = o3d.io.write_point_cloud(out_abs, pcd, write_ascii=write_ascii, compressed=not write_ascii)
    if ok:
        print(f'[OK] Wrote {out_abs} ({points.shape[0]} points)')
        if args.write_yaml:
            yaml_path = os.path.join(os.path.dirname(out_abs), 'pointcloud_map.yaml')
            try:
                with open(yaml_path, 'w', encoding='utf-8') as f:
                    f.write('pointcloud_map:\n')
                    f.write('  format: pcd\n')
                    f.write(f'  path: {os.path.basename(out_abs)}\n')
                print(f'[OK] Wrote {yaml_path}')
            except Exception as e:
                print(f'[WARN] Failed to write YAML: {e}')
    else:
        print('[ERROR] Failed to write PCD')


if __name__ == '__main__':
    main()
