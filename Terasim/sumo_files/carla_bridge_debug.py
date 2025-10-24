#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CARLA Bridge - Manual Walker Control (No NavMesh)
"""
import json, math, time, random
import redis
import carla
import numpy as np

# =========================
# Tunables
# =========================
MIN_SPEED_TO_WALK      = 0.20
MAX_WALK_SPEED         = 3.00
PEDESTRIAN_Z_OFFSET    = 0.0
EMA_ALPHA              = 0.35
PRINT_PERIOD_SEC       = 5.0

# Jaywalker settings
JAYWALK_SPEED          = 2.5
JAYWALKER_YAW_FOLLOW   = True
DESPAWN_AT_END         = True
DESPAWN_MARGIN         = 2.0

# Vehicle settings - KINEMATIC MODE (물리 OFF)
VEHICLE_KINEMATIC      = True   # ✅ kinematic 유지
VEHICLE_SMOOTH_ALPHA   = 0.3    # 보간 계수

# Loop timing
TICK_HZ                = 20.0
TICK_DT                = 1.0 / TICK_HZ

# =========================
# Helpers
# =========================
def clamp(v, lo, hi): 
    return max(lo, min(hi, v))

def is_jaywalker(pid: str) -> bool:
    p = pid.lower()
    return ("jay" in p) or ("jw" in p) or ("direct" in p)

# =========================
# Redis & CARLA
# =========================
r = redis.Redis(decode_responses=False)
ps = r.pubsub()
ps.subscribe("chan:tick")

client = carla.Client("127.0.0.1", 2000)
client.set_timeout(10.0)
world = client.get_world()

print("=" * 60)
print("CARLA Bridge - Manual Walker Control")
print("=" * 60)
print(f"Connected to CARLA world: {world.get_map().name}")

# =========================
# Coordinate Transform
# =========================
def sumo_to_carla(x_s, y_s):
    cfg = r.hgetall("sim:config")
    ox = float(cfg.get(b"origin_x", 0))
    oy = float(cfg.get(b"origin_y", 0))
    yaw_deg = float(cfg.get(b"yaw_deg", 0))
    z_base = float(cfg.get(b"z_base", 0.1))
    
    th = math.radians(yaw_deg)
    dx, dy = x_s - ox, y_s - oy
    X = math.cos(th) * dx - math.sin(th) * dy
    Y = -(math.sin(th) * dx + math.cos(th) * dy)
    Z = z_base
    return carla.Location(X, Y, Z)

def yaw_from_vector(dx, dy) -> float:
    """벡터에서 yaw 각도 계산"""
    return math.degrees(math.atan2(dy, dx))

# =========================
# State
# =========================
actors            = {}
ped_prev          = {}
ped_ema_dir       = {}
ped_ema_spd       = {}
veh_prev          = {}
completed_ped_ids = set()

bp_lib = world.get_blueprint_library()
vehicle_bp = bp_lib.find('vehicle.tesla.model3')
pedestrian_bps = bp_lib.filter('walker.pedestrian.*')

# =========================
# Spawners
# =========================
def ensure_vehicle(vid):
    if vid in actors and actors[vid].is_alive:
        return actors[vid]
    
    m = r.hgetall(f"sumo:veh:{vid}")
    if not m: 
        return None
    
    x = float(m.get(b"x", 0))
    y = float(m.get(b"y", 0))
    loc = sumo_to_carla(x, y)
    
    print(f"🚗 Spawning vehicle {vid} at ({loc.x:.1f}, {loc.y:.1f}, {loc.z:.1f})")
    
    bp = vehicle_bp
    if bp.has_attribute('color'):
        bp.set_attribute('color', '255,0,0')
    
    actor = world.try_spawn_actor(bp, carla.Transform(loc, carla.Rotation()))
    
    if actor:
        if VEHICLE_KINEMATIC:
            actor.set_simulate_physics(False)  # ✅ kinematic
            actor.set_enable_gravity(False)
        else:
            actor.set_simulate_physics(True)
        
        actors[vid] = actor
        veh_prev[vid] = (loc, 0.0)
        print(f"  ✓ Spawned (kinematic={VEHICLE_KINEMATIC})")
    else:
        print(f"  ✗ Failed")
    
    return actor

def ensure_pedestrian(pid):
    if pid in completed_ped_ids:
        return None
    if pid in actors and actors[pid].is_alive:
        return actors[pid]
    
    m = r.hgetall(f"sumo:ped:{pid}")
    if not m: 
        return None
    
    x = float(m.get(b"x", 0))
    y = float(m.get(b"y", 0))
    loc = sumo_to_carla(x, y)
    loc.z += PEDESTRIAN_Z_OFFSET
    
    print(f"🚶 Spawning pedestrian {pid} at ({loc.x:.1f}, {loc.y:.1f}, {loc.z:.1f})")
    
    bp = random.choice(pedestrian_bps)
    if bp.has_attribute('is_invincible'): 
        bp.set_attribute('is_invincible', 'true')
    
    # ✅ 보행자 스폰 (컨트롤러 없이)
    actor = world.try_spawn_actor(bp, carla.Transform(loc, carla.Rotation()))
    
    if actor:
        actors[pid] = actor
        tnow = time.time()
        ped_prev[pid]    = (loc, tnow)
        ped_ema_dir[pid] = np.array([0.0, 0.0])
        ped_ema_spd[pid] = 0.0
        print(f"  ✓ Spawned")
    else:
        print(f"  ✗ Failed")
    
    return actor

# =========================
# Map yaw
# =========================
try:
    yaw_deg_bytes = r.hget("sim:config", "yaw_deg")
    MAP_YAW_DEG = float(yaw_deg_bytes if yaw_deg_bytes else 0.0)
except Exception as e:
    MAP_YAW_DEG = 0.0

# =========================
# Pre-spawn
# =========================
print("\n🔍 Pre-spawn sweep...")
veh_count = 0
for key in r.scan_iter(match="sumo:veh:*", count=500):
    vid = key.decode().split(":")[-1]
    if ensure_vehicle(vid):
        veh_count += 1

ped_count = 0
for key in r.scan_iter(match="sumo:ped:*", count=500):
    pid = key.decode().split(":")[-1]
    if ensure_pedestrian(pid):
        ped_count += 1

print(f"Pre-spawned: {veh_count} vehicles, {ped_count} pedestrians\n")
print("🚀 Starting main loop...\n")

step_count   = 0
last_print   = time.time()
last_step    = time.time()

try:
    while True:
        now = time.time()
        
        # 비블로킹 PubSub
        msg = ps.get_message(ignore_subscribe_messages=True, timeout=0.0)
        sim_dt = None
        
        if msg and msg.get("type") == "message" and msg.get("channel") == b"chan:tick":
            try:
                payload = json.loads(msg["data"])
                sim_dt = float(payload.get("dt")) if "dt" in payload else None
            except Exception:
                pass
        
        # 주기 보장
        target_dt = sim_dt if (sim_dt and sim_dt > 0) else TICK_DT
        if (now - last_step) < target_dt:
            time.sleep(0.001)
            continue
        
        dt_used = target_dt
        last_step = now
        step_count += 1
        
        # 주기 출력
        if time.time() - last_print > PRINT_PERIOD_SEC:
            veh_keys = list(r.scan_iter(match="sumo:veh:*", count=500))
            ped_keys = list(r.scan_iter(match="sumo:ped:*", count=500))
            print(f"\n[{step_count:6d}] Status:")
            print(f"  Redis vehicles: {len(veh_keys)} | CARLA: {sum(1 for a in actors.values() if 'vehicle' in a.type_id)}")
            print(f"  Redis pedestrians: {len(ped_keys)} | CARLA: {sum(1 for a in actors.values() if 'walker' in a.type_id)}")
            last_print = time.time()
        
        # -----------------------
        # Vehicles (smooth kinematic)
        # -----------------------
        for key in r.scan_iter(match="sumo:veh:*", count=200):
            vid = key.decode().split(":")[-1]
            m = r.hgetall(key)
            if not m: 
                continue
            
            x = float(m.get(b"x", 0))
            y = float(m.get(b"y", 0))
            angle_s = float(m.get(b"angle", 0))
            sumo_speed = float(m.get(b"speed", 0)) # ✅ 속도 정보 읽기
            
            actor = ensure_vehicle(vid)
            if not actor: 
                continue
            
            target_loc = sumo_to_carla(x, y)
            target_yaw = angle_s - 90.0 - MAP_YAW_DEG
            
            if VEHICLE_KINEMATIC:
                # ✅ 부드러운 보간
                prev_loc, prev_yaw = veh_prev.get(vid, (target_loc, target_yaw))
                
                # 텔레포트 거리 체크
                distance = prev_loc.distance(target_loc)
                if distance > 5.0:
                    # 너무 멀면 즉시 이동
                    new_loc = target_loc
                    new_yaw = target_yaw
                    actor.set_transform(carla.Transform(new_loc, carla.Rotation(yaw=new_yaw)))
                else:
                    # 선형 보간
                    alpha = VEHICLE_SMOOTH_ALPHA
                    new_x = prev_loc.x + (target_loc.x - prev_loc.x) * alpha
                    new_y = prev_loc.y + (target_loc.y - prev_loc.y) * alpha
                    new_z = prev_loc.z + (target_loc.z - prev_loc.z) * alpha
                    
                    # 각도 보간
                    yaw_diff = (target_yaw - prev_yaw + 180) % 360 - 180
                    new_yaw = prev_yaw + yaw_diff * alpha
                    
                    new_loc = carla.Location(new_x, new_y, new_z)
                    actor.set_transform(carla.Transform(new_loc, carla.Rotation(yaw=new_yaw)))
                
                # ✅ 수정: 바퀴 회전을 위한 속도 설정
                # set_transform 후 set_target_velocity를 호출하여 휠 애니메이션을 유도
                try:
                    yaw_rad = math.radians(new_yaw) # 보간된 yaw 사용
                    vx = sumo_speed * math.cos(yaw_rad)
                    vy = sumo_speed * math.sin(yaw_rad)
                    actor.set_target_velocity(carla.Vector3D(x=vx, y=vy, z=0))
                except Exception as e:
                    print(f"Warn: Failed to set target velocity for {vid}: {e}")
                
                # 다음 보간을 위해 '목표' 위치/각도 저장 (보간된 new_loc 아님)
                veh_prev[vid] = (target_loc, target_yaw) 
        
        # -----------------------
        # Pedestrians (manual WalkerControl)
        # -----------------------
        now_sys = time.time()
        for key in r.scan_iter(match="sumo:ped:*", count=200):
            pid = key.decode().split(":")[-1]
            m = r.hgetall(key)
            if not m:
                continue
            if pid in completed_ped_ids:
                continue
            
            x = float(m.get(b"x", 0))
            y = float(m.get(b"y", 0))
            target_loc = sumo_to_carla(x, y)
            target_loc.z += PEDESTRIAN_Z_OFFSET
            
            actor = ensure_pedestrian(pid)
            if not actor:
                continue
            
            prev_loc, prev_t = ped_prev.get(pid, (target_loc, now_sys))
            
            # ✅ 수정: 스폰 즉시 삭제 방지용 시간차 계산
            dt_sys = now_sys - prev_t
            
            # ✅ 이동 방향 계산 (이전 목표 위치 -> 현재 목표 위치 기준)
            dx = target_loc.x - prev_loc.x
            dy = target_loc.y - prev_loc.y
            d = math.hypot(dx, dy)
            
            # 도착 체크
            # ✅ 수정: dt_sys > 0.1 조건을 추가하여 스폰 직후 삭제 방지
            if d < DESPAWN_MARGIN and dt_sys > 0.1 and DESPAWN_AT_END and is_jaywalker(pid):
                try:
                    actor.destroy()
                except:
                    pass
                actors.pop(pid, None)
                ped_prev.pop(pid, None)
                ped_ema_dir.pop(pid, None)
                ped_ema_spd.pop(pid, None)
                completed_ped_ids.add(pid)
                print(f"🏁 {pid} completed")
                continue
            
            # 속도 계산 (dt_used는 시뮬레이션 스텝 간격)
            inst_speed = clamp(d / dt_used, 0.0, MAX_WALK_SPEED)
            
            if d >= 0.01:  # 최소 이동 거리
                ux, uy = dx / d, dy / d
            else:
                ux, uy = 0.0, 0.0
            
            # EMA 평활
            e_dir = ped_ema_dir.get(pid, np.array([ux, uy], dtype=float))
            e_spd = ped_ema_spd.get(pid, float(inst_speed))
            
            e_dir = (1.0 - EMA_ALPHA) * e_dir + EMA_ALPHA * np.array([ux, uy], dtype=float)
            norm = np.linalg.norm(e_dir)
            if norm > 1e-6:
                e_dir = e_dir / norm
            
            e_spd = (1.0 - EMA_ALPHA) * e_spd + EMA_ALPHA * float(inst_speed)
            speed = clamp(float(e_spd), 0.0, MAX_WALK_SPEED)
            
            # ✅ WalkerControl 적용
            direction = carla.Vector3D(float(e_dir[0]), float(e_dir[1]), 0.0)
            
            if speed >= MIN_SPEED_TO_WALK:
                control = carla.WalkerControl(direction=direction, speed=speed, jump=False)
                actor.apply_control(control)
                
                # 방향에 맞춰 yaw 조정 (선택)
                if JAYWALKER_YAW_FOLLOW and is_jaywalker(pid):
                    yaw = yaw_from_vector(e_dir[0], e_dir[1])
                    current_transform = actor.get_transform()
                    new_transform = carla.Transform(
                        current_transform.location,
                        carla.Rotation(yaw=yaw)
                    )
                    # set_transform 대신 set_target_transform을 사용하면 더 부드러울 수 있습니다.
                    actor.set_transform(new_transform) 
            else:
                # 정지
                control = carla.WalkerControl(
                    direction=carla.Vector3D(0, 0, 0), 
                    speed=0.0, 
                    jump=False
                )
                actor.apply_control(control)
            
            # 현재 목표 위치를 '이전 위치'로 저장 (다음 프레임에서 사용)
            ped_prev[pid] = (target_loc, now_sys) 
            ped_ema_dir[pid] = e_dir
            ped_ema_spd[pid] = e_spd

except KeyboardInterrupt:
    print("\n\nStopped by user")
finally:
    print("Cleaning up actors...")
    # 액터 삭제 시에도 try-except로 감싸는 것이 안전합니다.
    for actor_id, actor in list(actors.items()):
        try:
            if actor and actor.is_alive:
                actor.destroy()
        except Exception as e:
            print(f"Error destroying actor {actor_id}: {e}")
    print("Done")






