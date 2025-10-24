#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SUMO Bridge - Fixed Pedestrian Tracking
"""
import os, sys, time, json, redis, math

# 파라미터
SAFE_DISTANCE        = 25.0
EMERGENCY_DISTANCE   = 12.0
SLOWDOWN_DURATION    = 3.5
FORCE_CROSSING       = True
CORRIDOR_HALF_WIDTH  = 4.5
ENTER_MARGIN         = 8.0
EXIT_MARGIN          = 4.0
DIR_EMA_ALPHA        = 0.2
MIN_STEP_FOR_DIR     = 0.3
PREDICTION_TIME      = 3.0

SUMO_HOME = os.environ.get("SUMO_HOME", "/usr/share/sumo")
sys.path.insert(0, os.path.join(SUMO_HOME, "tools"))
from sumolib import checkBinary
import traci

print("=" * 60)
print("SUMO Bridge - Fixed Pedestrian Tracking")
print("=" * 60)

r = redis.Redis(decode_responses=False)
ps = r.pubsub()
ps.subscribe("chan:tick")

SUMO_BIN = checkBinary("sumo")
sumo_cmd = [
    SUMO_BIN,
    "-c", "targeted.sumocfg",
    "--step-length", "0.05",
    "--collision.action", "warn",
    "--collision.mingap-factor", "0",
    "--no-warnings"
]

print(f"Starting: {' '.join(sumo_cmd)}")
traci.start(sumo_cmd)
print("✓ SUMO started!")

def get_distance(x1, y1, x2, y2):
    return math.hypot(x2 - x1, y2 - y1)

def is_jay(pid: str) -> bool:
    p = pid.lower()
    return ("jay" in p) or ("jw" in p) or ("direct" in p)

def angle_diff(a1, a2):
    diff = (a2 - a1 + 180) % 360 - 180
    return abs(diff)

jw_corridor = {}
jw_prev_pos = {}
vehicle_stop_state = {}
vehicle_history = {}

print("\n[Starting loop...]")
step_count = 0
last_print = time.time()
ped_seen = set()  # ✅ 추가: 본 적 있는 보행자 추적

try:
    for msg in ps.listen():
        if msg["type"] != "message" or msg.get("channel") != b"chan:tick":
            continue

        try:
            tick = json.loads(msg["data"])
            t = float(tick.get("t")) if "t" in tick else traci.simulation.getTime()
        except Exception:
            t = traci.simulation.getTime()

        step_count += 1

        # ----- 차량 상태 수집 -----
        vehicle_positions = {}
        for vid in traci.vehicle.getIDList():
            try:
                x, y = traci.vehicle.getPosition(vid)
                angle = traci.vehicle.getAngle(vid)
                speed = traci.vehicle.getSpeed(vid)
                edge = traci.vehicle.getRoadID(vid)
                pos = traci.vehicle.getLanePosition(vid)
                
                vehicle_positions[vid] = {
                    'x': x, 'y': y, 'speed': speed, 'angle': angle,
                    'edge': edge, 'pos': pos
                }
                
                r.hset(f"sumo:veh:{vid}", mapping={
                    "x": x, "y": y, "edge": edge, "pos": pos,
                    "speed": speed, "angle": angle, "time": t
                })
                
                if vid not in vehicle_history:
                    vehicle_history[vid] = []
                vehicle_history[vid].append((x, y, t))
                vehicle_history[vid] = [(vx, vy, vt) for vx, vy, vt in vehicle_history[vid] 
                                       if t - vt < 5.0]
                
            except Exception as e:
                print(f"Error reading vehicle {vid}: {e}")

        # ----- 보행자 상태 수집 -----
        pedestrian_positions = {}
        person_list = traci.person.getIDList()
        
        # ✅ 디버깅: 보행자 목록 출력
        if len(person_list) > 0 and step_count % 50 == 0:
            print(f"\n  🚶 SUMO has {len(person_list)} pedestrians: {list(person_list)}")
        
        for pid in person_list:
            try:
                x, y = traci.person.getPosition(pid)
                edge = traci.person.getRoadID(pid)
                pos = traci.person.getLanePosition(pid)
                
                pedestrian_positions[pid] = (x, y)
                
                # ✅ 첫 발견 시 출력
                if pid not in ped_seen:
                    print(f"  ✨ New pedestrian detected: '{pid}' at ({x:.1f}, {y:.1f})")
                    ped_seen.add(pid)
                
                # Jaywalker 강제 속도
                if is_jay(pid) and FORCE_CROSSING:
                    try:
                        traci.person.setSpeed(pid, 2.5)
                    except Exception:
                        pass
                
                # ✅ Redis 저장 (바이트 키 사용)
                redis_key = f"sumo:ped:{pid}"
                r.hset(redis_key, mapping={
                    "x": x, "y": y, "edge": edge, "pos": pos, "time": t
                })
                
                # ✅ Redis 저장 확인 (첫 발견 시 또는 100 스텝마다)
                if pid not in ped_seen or step_count % 100 == 0:
                    verify = r.exists(redis_key)
                    if verify:
                        print(f"  ✅ Redis key created: {redis_key}")
                    else:
                        print(f"  ❌ Redis key NOT created: {redis_key}")
                
                # 회랑 추정
                if is_jay(pid):
                    if pid not in jw_corridor:
                        jw_corridor[pid] = {
                            "start": (x, y),
                            "dir": None,
                            "length_est": 0.0,
                            "samples": 0
                        }
                        jw_prev_pos[pid] = (x, y)
                    else:
                        px, py = jw_prev_pos.get(pid, (x, y))
                        dx, dy = (x - px), (y - py)
                        d = math.hypot(dx, dy)
                        
                        if d >= MIN_STEP_FOR_DIR:
                            ux, uy = dx / d, dy / d
                            cur_dir = jw_corridor[pid]["dir"]
                            
                            if cur_dir is None:
                                new_dir = (ux, uy)
                                jw_corridor[pid]["samples"] = 1
                            else:
                                ex = (1 - DIR_EMA_ALPHA) * cur_dir[0] + DIR_EMA_ALPHA * ux
                                ey = (1 - DIR_EMA_ALPHA) * cur_dir[1] + DIR_EMA_ALPHA * uy
                                n = math.hypot(ex, ey)
                                new_dir = (ex / n, ey / n) if n > 1e-6 else cur_dir
                                jw_corridor[pid]["samples"] += 1
                            
                            jw_corridor[pid]["dir"] = new_dir
                            sx, sy = jw_corridor[pid]["start"]
                            current_length = math.hypot(x - sx, y - sy)
                            jw_corridor[pid]["length_est"] = max(
                                jw_corridor[pid]["length_est"], 
                                current_length
                            )
                            jw_prev_pos[pid] = (x, y)
                            
            except Exception as e:
                print(f"Error reading pedestrian {pid}: {e}")

        # ----- SUMO에서 사라진 보행자 정리 -----
        alive = set(traci.person.getIDList())
        for key in r.scan_iter(match="sumo:ped:*", count=200):
            pid = key.decode().split(":")[-1]
            if pid not in alive:
                r.delete(key)
                jw_corridor.pop(pid, None)
                jw_prev_pos.pop(pid, None)
                print(f"  🗑️  Removed pedestrian {pid} from Redis")

        # ----- 차량 제어 (이전과 동일) -----
        cars_that_must_stop = set()
        cars_that_must_slow_down = set()
        stop_reasons = {}

        for pid, (px, py) in pedestrian_positions.items():
            if not is_jay(pid):
                continue
            
            cor = jw_corridor.get(pid)
            has_cor = cor and (cor.get("dir") is not None) and (cor.get("samples", 0) >= 3)
            
            if has_cor:
                sx, sy = cor["start"]
                ux, uy = cor["dir"]
                Lest = max(8.0, cor["length_est"])
            
            for vid, vdata in vehicle_positions.items():
                vx, vy = vdata['x'], vdata['y']
                vspeed = vdata['speed']
                vangle = vdata['angle']
                
                distance = get_distance(vx, vy, px, py)
                
                if distance < SAFE_DISTANCE:
                    angle_rad = math.radians(vangle)
                    fwd_x = math.sin(angle_rad)
                    fwd_y = math.cos(angle_rad)
                    ped_vec_x = px - vx
                    ped_vec_y = py - vy
                    dot_product = fwd_x * ped_vec_x + fwd_y * ped_vec_y
                    
                    if dot_product > 0:
                        if distance < EMERGENCY_DISTANCE:
                            cars_that_must_stop.add(vid)
                            stop_reasons[vid] = f"EMERGENCY: ped {pid} at {distance:.1f}m"
                        elif distance < SAFE_DISTANCE:
                            if vid not in cars_that_must_stop:
                                cars_that_must_slow_down.add(vid)
                                stop_reasons[vid] = f"SLOWDOWN: ped {pid} at {distance:.1f}m"
                
                if has_cor:
                    rx, ry = (vx - sx), (vy - sy)
                    s = rx * ux + ry * uy
                    cx, cy = sx + s * ux, sy + s * uy
                    lat = math.hypot(vx - cx, vy - cy)
                    
                    in_corridor_range = (-ENTER_MARGIN <= s <= Lest + EXIT_MARGIN)
                    in_corridor_width = (lat <= CORRIDOR_HALF_WIDTH)
                    
                    if in_corridor_range and in_corridor_width:
                        angle_rad = math.radians(vangle)
                        fwd_x = math.sin(angle_rad)
                        fwd_y = math.cos(angle_rad)
                        cor_angle = math.degrees(math.atan2(uy, ux))
                        angle_to_corridor = angle_diff(vangle, cor_angle)
                        cor_vec_x = cx - vx
                        cor_vec_y = cy - vy
                        dot_cor = (fwd_x * cor_vec_x + fwd_y * cor_vec_y)
                        
                        if dot_cor > 0 and angle_to_corridor < 90:
                            if lat < 2.5 or s < 5.0:
                                cars_that_must_stop.add(vid)
                                stop_reasons[vid] = f"CORRIDOR_EMERGENCY: {lat:.1f}m lateral"
                            elif lat < CORRIDOR_HALF_WIDTH:
                                if vid not in cars_that_must_stop:
                                    cars_that_must_slow_down.add(vid)
                                    stop_reasons[vid] = f"CORRIDOR_APPROACH: {lat:.1f}m lateral"
                
                if vspeed > 0.5:
                    angle_rad = math.radians(vangle)
                    predicted_x = vx + vspeed * PREDICTION_TIME * math.sin(angle_rad)
                    predicted_y = vy + vspeed * PREDICTION_TIME * math.cos(angle_rad)
                    
                    if has_cor:
                        pred_px = px + 2.5 * PREDICTION_TIME * ux
                        pred_py = py + 2.5 * PREDICTION_TIME * uy
                    else:
                        pred_px, pred_py = px, py
                    
                    pred_distance = get_distance(predicted_x, predicted_y, pred_px, pred_py)
                    
                    if pred_distance < 8.0:
                        if vid not in cars_that_must_stop:
                            cars_that_must_slow_down.add(vid)
                            stop_reasons[vid] = f"PREDICTED_COLLISION: {pred_distance:.1f}m"

        # ----- 차량 제어 적용 -----
        for vid in vehicle_positions.keys():
            if vid not in vehicle_stop_state:
                vehicle_stop_state[vid] = {"stopped": False, "stop_time": 0.0, "reason": ""}
            
            state = vehicle_stop_state[vid]
            is_currently_stopped = state["stopped"]
            
            if vid in cars_that_must_stop:
                if not is_currently_stopped:
                    try:
                        traci.vehicle.setSpeed(vid, 0)
                        state["stopped"] = True
                        state["stop_time"] = t
                        state["reason"] = stop_reasons.get(vid, "unknown")
                        print(f"🛑 {vid} STOPPED: {state['reason']}")
                    except Exception as e:
                        print(f"Error stopping {vid}: {e}")
                        
            elif vid in cars_that_must_slow_down:
                if not is_currently_stopped:
                    try:
                        current_speed = vehicle_positions[vid]['speed']
                        target_speed = min(2.0, current_speed * 0.3)
                        traci.vehicle.slowDown(vid, target_speed, SLOWDOWN_DURATION)
                        state["stopped"] = True
                        state["stop_time"] = t
                        state["reason"] = stop_reasons.get(vid, "unknown")
                        print(f"⚠️  {vid} SLOWING: {state['reason']}")
                    except Exception as e:
                        print(f"Error slowing {vid}: {e}")
                        
            else:
                if is_currently_stopped:
                    time_stopped = t - state["stop_time"]
                    min_jay_distance = float('inf')
                    for pid, (px, py) in pedestrian_positions.items():
                        if is_jay(pid):
                            vx, vy = vehicle_positions[vid]['x'], vehicle_positions[vid]['y']
                            d = get_distance(vx, vy, px, py)
                            min_jay_distance = min(min_jay_distance, d)
                    
                    if time_stopped > 2.0 and min_jay_distance > 15.0:
                        try:
                            traci.vehicle.setSpeed(vid, -1)
                            state["stopped"] = False
                            state["stop_time"] = 0.0
                            print(f"✅ {vid} RESUMING (clear: {min_jay_distance:.1f}m)")
                        except Exception as e:
                            print(f"Error resuming {vid}: {e}")

        # ----- 주기 출력 -----
        if time.time() - last_print > 5.0:
            num_veh = len(vehicle_positions)
            num_ped = len(pedestrian_positions)
            stopped_count = sum(1 for s in vehicle_stop_state.values() if s["stopped"])
            jay_count = sum(1 for pid in pedestrian_positions if is_jay(pid))
            
            # ✅ Redis 키 수 확인
            redis_ped_keys = list(r.scan_iter(match="sumo:ped:*", count=500))
            
            print(f"\n[{step_count:6d}] t={t:7.2f}s")
            print(f"  Vehicles: {num_veh} (stopped: {stopped_count})")
            print(f"  Pedestrians: {num_ped} (jaywalkers: {jay_count})")
            print(f"  Redis pedestrian keys: {len(redis_ped_keys)}")  # ✅ 추가
            
            for vid, state in vehicle_stop_state.items():
                if state["stopped"]:
                    print(f"    - {vid}: {state['reason']} ({t - state['stop_time']:.1f}s)")
            
            last_print = time.time()

        try:
            traci.simulationStep()
        except Exception as e:
            if "connection" in str(e).lower():
                print("\nSimulation ended")
                break
            else:
                print(f"Step error: {e}")

except KeyboardInterrupt:
    print("\nStopped by user")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
finally:
    try:
        traci.close()
    except Exception:
        pass
    print("SUMO Bridge terminated")

	


