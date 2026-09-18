"""Dedicated-server survey with measurement-time transforms and recovery."""
import hashlib
import json
import math
from pathlib import Path
import queue
import time
import numpy as np
from .common import fingerprint, write_json
from .cloud import VoxelStore, measurement_points


class Inbox:
    def __init__(self,size=4):
        self.queue=queue.Queue(maxsize=size); self.dropped=0; self.late=0

    def put(self,measurement):
        try: self.queue.put_nowait(measurement)
        except queue.Full: self.dropped+=1

    def frame(self,expected,timeout):
        deadline=time.monotonic()+timeout
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0: raise TimeoutError(f'No LiDAR scan for frame {expected}')
            try: measurement=self.queue.get(timeout=remaining)
            except queue.Empty: raise TimeoutError(f'No LiDAR scan for frame {expected}') from None
            if measurement.frame<expected: self.late+=1; continue
            if measurement.frame>expected: raise RuntimeError(f'Unexpected future LiDAR frame {measurement.frame}, expected {expected}; another client may be ticking')
            return measurement


def connect(host,port,map_name=None):
    import carla
    client=carla.Client(host,port); client.set_timeout(120.)
    versions=(client.get_client_version(),client.get_server_version())
    if any(v.split('-')[0]!='0.9.16' for v in versions): raise ValueError(f'Require CARLA 0.9.16 server and bindings, got {versions}')
    world=client.get_world()
    occupied=[a.type_id for a in world.get_actors() if a.type_id.startswith(('vehicle.','walker.','sensor.'))]
    if occupied: raise RuntimeError(f'Dedicated mapping server required; active actors: {occupied[:8]}')
    if map_name is not None:
        available=client.get_available_maps()
        matches=[m for m in available if m==map_name or m.rsplit('/',1)[-1]==map_name]
        if len(matches)!=1: raise ValueError(f'Map {map_name!r} is not an unambiguous advertised map; available: {available}')
        if world.get_map().name.rsplit('/',1)[-1]!=matches[0].rsplit('/',1)[-1]: world=client.load_world(matches[0])
    return client,world


def runtime_evidence(world,network):
    """Snapshot native source IDs and geometry; never infer individual bulbs."""
    result=dict(map=world.get_map().name,traffic_lights=[],landmarks=[],topology=[])
    cmap=world.get_map()
    def waypoint(w):
        p=w.transform.location
        return dict(road=str(w.road_id),lane=w.lane_id,s=w.s,xyz=[p.x,-p.y,p.z])
    for a,b in cmap.get_topology(): result['topology'].append([waypoint(a),waypoint(b)])
    for lm in cmap.get_all_landmarks():
        result['landmarks'].append({k:getattr(lm,k,None) for k in ('id','name','road_id','s','t','type','sub_type','value','unit')})
    for actor in world.get_actors().filter('traffic.traffic_light*'):
        source_id=actor.get_opendrive_id()
        stops=[waypoint(w) for w in actor.get_stop_waypoints()]
        affected=[waypoint(w) for w in actor.get_affected_lane_waypoints()]
        boxes=[]
        for box in actor.get_light_boxes():
            # get_light_boxes returns world-space boxes in CARLA 0.9.16.
            boxes.append(dict(center=[box.location.x,-box.location.y,box.location.z],extent=[box.extent.x,box.extent.y,box.extent.z],rotation=[box.rotation.pitch,box.rotation.yaw,box.rotation.roll]))
        entry=dict(actor_id=actor.id,opendrive_id=source_id,stop_waypoints=stops,affected_lanes=affected,light_boxes=boxes)
        result['traffic_lights'].append(entry)
        matches=[c for c in network.controls.values() if c['id']==source_id and c['kind']=='traffic_light']
        if len(matches)!=1:
            network.diagnostics.add('runtime_control_id',str(source_id),'Runtime signal cannot be mapped uniquely to OpenDRIVE','regulatory'); continue
        c=matches[0]; c['runtime']=entry
        c['lanes']=sorted(set(c['lanes']) | {l.key for l in network.lanes.values() for w in affected if l.road==w['road'] and l.lane_id==w['lane'] and l.start-1e-3<=w['s']<=l.end+1e-3})
        # Only an unambiguous single stop cross-section can become one ref_line.
        if len(stops)==1 and not c.get('stop_line'):
            w=stops[0]
            candidates=[l for l in network.lanes.values() if l.road==w['road'] and l.lane_id==w['lane'] and l.start-1e-3<=w['s']<=l.end+1e-3]
            if candidates:
                l=candidates[0]; road=network.roads[l.road]; inner=l.lane_id-(1 if l.lane_id>0 else -1)
                c['stop_line']=[road.boundary(l.section,i,w['s']).tolist() for i in (inner,l.lane_id)]
        if boxes:
            network.diagnostics.add('runtime_light_boxes',c['source'],'Light boxes recorded; individual bulb colors/positions and facing geometry still require corrections','regulatory',severity='warning')
    # Compare the independently evaluated source surface to CARLA waypoints in 3D.
    max_error=0.; mismatches=0
    for lane in network.lanes.values():
        s=(lane.start+lane.end)/2
        wp=cmap.get_waypoint_xodr(int(lane.road),lane.lane_id,s)
        if wp is None:
            network.diagnostics.add('runtime_lane_missing',lane.key,'CARLA exposes no waypoint for generated lane'); continue
        road=network.roads[lane.road]; inner=lane.lane_id-(1 if lane.lane_id>0 else -1)
        xyz=(road.boundary(lane.section,inner,s)+road.boundary(lane.section,lane.lane_id,s))/2
        p=wp.transform.location; error=float(np.linalg.norm(xyz-[p.x,-p.y,p.z])); max_error=max(max_error,error)
        if error>network.config['surface_tolerance']:
            mismatches+=1; network.diagnostics.add('scene_source_surface',lane.key,f'CARLA/source center surface differs by {error:.3f} m; inspect banking/mesh alignment')
    result['surface_comparison']=dict(max_error_m=max_error,mismatches=mismatches)
    return result


def capture(client,world,network,stations,directory,resume=False,limit=None):
    import carla
    directory=Path(directory); config=network.config
    if fingerprint(world.get_map().to_opendrive())!=network.fingerprint: raise ValueError('Loaded CARLA map does not match source fingerprint')
    identity=dict(version=1,source_fingerprint=network.fingerprint,correction_hash=network.correction_hash,config=config,
                  stations_hash=hashlib.sha256(json.dumps(stations,sort_keys=True).encode()).hexdigest(),map=world.get_map().name)
    store=VoxelStore(directory/'capture',identity,config,resume)
    old=world.get_settings(); spectator=world.get_spectator(); old_spectator=spectator.get_transform()
    sensor=None; inbox=Inbox(); failure=None; cleanup=[]
    previous_frame=None; accepted=0; completed=store.completed()
    manifest=dict(identity=identity,total_stations=len(stations),completed_stations=len(completed),status='capturing',
                  intensity='synthetic exp(-0.004 * range_m); not material reflectance',runtime_checks={})
    # Conservative upper bound for arrays + queued raw scans; enforce before spawning.
    scan_bytes=config['channels']*config['horizontal_samples']*24
    if scan_bytes*(8+config['sweeps']*5)>config['memory_mib']*1024**2*.6:
        store.close(); raise ValueError('Sensor configuration exceeds collector memory budget')
    try:
        settings=world.get_settings(); settings.synchronous_mode=True; settings.fixed_delta_seconds=config['delta']; settings.no_rendering_mode=True
        settings.substepping=True; settings.max_substep_delta_time=.01; settings.max_substeps=math.ceil(config['delta']/.01)
        settings.tile_stream_distance=config['streaming_distance']; settings.actor_active_distance=config['streaming_distance']; settings.spectator_as_ego=True
        world.apply_settings(settings)
        bp=world.get_blueprint_library().find('sensor.lidar.ray_cast_semantic')
        attrs=dict(channels=str(config['channels']),range=str(config['range']),rotation_frequency=str(1/config['delta']),
                   points_per_second=str(round(config['channels']*config['horizontal_samples']/config['delta'])),
                   upper_fov=str(config['upper_fov']),lower_fov=str(config['lower_fov']),sensor_tick='0.0')
        for k,v in attrs.items(): bp.set_attribute(k,v)
        sensor=world.spawn_actor(bp,carla.Transform()); sensor.listen(inbox.put)
        def tick():
            nonlocal previous_frame
            if previous_frame is not None and world.get_snapshot().frame!=previous_frame:
                raise RuntimeError('World advanced between survey ticks; conflicting ticker detected')
            frame=world.tick(config['scan_timeout'])
            if previous_frame is not None and frame!=previous_frame+1:
                raise RuntimeError('Nonconsecutive frame; conflicting ticker detected')
            previous_frame=frame
            return frame
        for station in stations:
            if station['id'] in completed: continue
            if limit is not None and accepted>=limit: break
            x,y,z=station['xyz']; spectator.set_transform(carla.Transform(carla.Location(x,-y,z+config['height'])))
            scans=[]; stats=[]
            for sweep in range(config['sweeps']):
                phase=sweep/config['sweeps']
                desired=carla.Transform(carla.Location(x,-y,z+config['height']),carla.Rotation(
                    pitch=station['pitch']+phase*(config['upper_fov']-config['lower_fov'])/max(1,config['channels']-1),
                    yaw=-station['yaw']+phase*360/config['horizontal_samples'],roll=-station['roll']))
                last_error=None
                for attempt in range(config['retries']):
                    responses=client.apply_batch_sync([carla.command.ApplyTransform(sensor.id,desired)],False)
                    if responses[0].has_error(): raise RuntimeError(responses[0].error)
                    try:
                        frame=tick(); measurement=inbox.frame(frame,config['scan_timeout'])
                        actual=np.asarray(measurement.transform.get_matrix()); expected=np.asarray(desired.get_matrix())
                        if not np.allclose(actual,expected,atol=.02,rtol=0):
                            last_error='LiDAR measurement has a stale pose'; continue
                        # A road-labelled return near THIS road's 3D surface verifies streaming.
                        points,labels,removed=measurement_points(measurement)
                        # A LiDAR has a nadir blind spot: validate the road directly
                        # below the station using CARLA's collision ray, not a
                        # nonexistent near-vertical LiDAR channel.
                        hits=world.cast_ray(carla.Location(x,-y,z+config['height']),carla.Location(x,-y,z-config['surface_tolerance']-1.))
                        loaded=any(int(hit.label) in (1,24,25) and abs(hit.location.z-z)<=config['surface_tolerance'] for hit in hits)
                        if not loaded:
                            last_error='Nearby road surface not loaded or scene/OpenDRIVE surface mismatch'; continue
                        scans.append(points); stats.append(dict(frame=frame,points=len(points),labels=labels,dynamic_removed=removed,attempts=attempt+1))
                        break
                    except TimeoutError as ex: last_error=str(ex)
                else: raise RuntimeError(f'Station {station["id"]}, sweep {sweep}: {last_error}; resume after checking streaming and scene alignment')
            store.commit_station(station['id'],scans,dict(scans=stats,xyz=station['xyz']))
            completed.add(station['id']); accepted+=1
            manifest.update(completed_stations=len(completed),last_station=station['id'],late_scans=inbox.late,dropped_scans=inbox.dropped)
            write_json(directory/'capture.json',manifest)
            if accepted%25==0: print(f'Captured {len(completed)}/{len(stations)} stations',flush=True)
        manifest['files']=store.export(directory)
        manifest.update(status='complete' if len(completed)==len(stations) else 'partial',points=store.count())
        manifest['runtime_checks']['live_capture']=dict(status='passed' if len(completed)==len(stations) else 'partial',stations=len(completed))
    except BaseException as ex:
        failure=ex; manifest.update(status='interrupted' if isinstance(ex,KeyboardInterrupt) else 'failed',error=str(ex),completed_stations=len(store.completed()))
    finally:
        if sensor is not None:
            try: sensor.stop(); sensor.destroy()
            except Exception as ex: cleanup.append('sensor: '+str(ex))
        try: spectator.set_transform(old_spectator)
        except Exception as ex: cleanup.append('spectator: '+str(ex))
        try: world.apply_settings(old)
        except Exception as ex: cleanup.append('settings: '+str(ex))
        store.close(); manifest['cleanup_errors']=cleanup
        if cleanup: manifest['status']='failed'
        try: write_json(directory/'capture.json',manifest)
        except OSError:
            if failure is None: raise
    if failure is not None: raise failure
    if cleanup: raise RuntimeError('Capture cleanup failed: '+str(cleanup))
    return manifest
