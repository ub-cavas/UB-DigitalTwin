#!/usr/bin/env python3
"""Offline-positioned semantic LiDAR survey of an existing Lanelet corridor.

Run against a dedicated CARLA server. Produces an XYZI binary PCD in Autoware
Local coordinates, retaining the map origin. No driving/autopilot is required.
Requires CARLA and NumPy. It never overwrites the installed point cloud.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import queue
import time
import xml.etree.ElementTree as ET

import carla
import numpy as np

SEMANTIC = np.dtype([('x','<f4'),('y','<f4'),('z','<f4'),
                     ('cosine','<f4'),('object','<u4'),('label','<u4')])
DYNAMIC_NAMES = ('Pedestrians','Rider','Car','Truck','Bus','Train','Motorcycle',
                 'Bicycle','Dynamic','Vehicles','AnimatedCharacters')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024**2), b''):
            h.update(block)
    return h.hexdigest()


def interpolate(points, fractions):
    distance = np.r_[0, np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    if distance[-1] == 0:
        raise ValueError('Zero length lane boundary')
    return np.column_stack([np.interp(fractions, distance / distance[-1], points[:, i]) for i in range(3)])


def survey_poses(path, spacing):
    root = ET.parse(path).getroot()
    nodes = {}
    for n in root.findall('node'):
        t = {t.get('k'): t.get('v') for t in n.findall('tag')}
        nodes[n.get('id')] = [float(t['local_x']), float(t['local_y']), float(t.get('ele',0))]
    ways = {w.get('id'): np.array([nodes[n.get('ref')] for n in w.findall('nd')]) for w in root.findall('way')}
    poses = []
    for rel in root.findall('relation'):
        if rel.find("tag[@k='type']").get('v') != 'lanelet':
            continue
        left = ways[rel.find("member[@role='left']").get('ref')]
        right = ways[rel.find("member[@role='right']").get('ref')]
        if np.linalg.norm(left[0]-right[-1])+np.linalg.norm(left[-1]-right[0]) < np.linalg.norm(left[0]-right[0])+np.linalg.norm(left[-1]-right[-1]):
            right = right[::-1]
        length = max(np.linalg.norm(np.diff(p,axis=0),axis=1).sum() for p in [left,right])
        ts = np.linspace(0,1,max(2,math.ceil(length / spacing)+1))
        centers = (interpolate(left,ts)+interpolate(right,ts))/2
        for p in centers:
            poses.append([float(v) for v in p] + [int(rel.get('id'))])
    # Repeated junction centers add no information to a stationary 360° survey.
    result = []; seen = set()
    for p in poses:
        key = tuple(np.round(np.array(p[:3]) / 0.5).astype(int))
        if key not in seen:
            seen.add(key); result.append(p)
    return np.array(result)


def voxel_keys(points, voxel):
    cells = np.floor(points[:, :3].astype(np.float64) / voxel).astype(np.int64)
    limit = 1 << 20
    if np.any(cells < -limit) or np.any(cells >= limit):
        raise ValueError('Point coordinates exceed voxel index range')
    cells += limit
    return (cells[:,0] << 42) | (cells[:,1] << 21) | cells[:,2]


def reduce_cloud(points, voxel):
    keys = voxel_keys(points, voxel)
    _, indices = np.unique(keys, return_index=True)
    # Keep an actual surface return; averaging across thin surfaces can blur them.
    return points[indices]


def measurement_points(measurement, excluded):
    data = np.frombuffer(measurement.raw_data, dtype=SEMANTIC)
    keep = ~np.isin(data['label'], excluded)
    xyz = np.column_stack([data[k][keep] for k in ('x','y','z')])
    finite = np.isfinite(xyz).all(axis=1)
    xyz = xyz[finite]
    distance = np.linalg.norm(xyz,axis=1)
    keep_distance = distance > 0.5
    xyz, distance = xyz[keep_distance], distance[keep_distance]
    # Use the transform carried by THIS scan, not the sensor's later live pose.
    matrix = np.asarray(measurement.transform.get_matrix(),dtype=np.float64)
    world = xyz @ matrix[:3,:3].T + matrix[:3,3]
    world[:,1] *= -1  # CARLA left-handed -> Autoware local ENU
    # CARLA RayCastLidar's default range attenuation model; this is synthetic
    # intensity, not material reflectivity or the semantic incidence cosine.
    intensity = np.exp(-0.004 * distance)
    return np.column_stack([world,intensity]).astype('<f4'), Counter(dict(zip(*np.unique(data['label'],return_counts=True)))), int((~keep).sum())


def write_pcd(path, points):
    header = ('# .PCD v0.7 - Point Cloud Data file format\nVERSION 0.7\n'
              'FIELDS x y z intensity\nSIZE 4 4 4 4\nTYPE F F F F\nCOUNT 1 1 1 1\n'
              f'WIDTH {len(points)}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {len(points)}\nDATA binary\n')
    temp = path.with_suffix('.pcd.tmp')
    with temp.open('wb') as f:
        f.write(header.encode('ascii'))
        points.astype('<f4',copy=False).tofile(f)
    temp.replace(path)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host',default='127.0.0.1')
    p.add_argument('--port',type=int,default=2100)
    p.add_argument('--lanelet',type=Path,required=True)
    p.add_argument('--opendrive',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--spacing',type=float,default=3.0)
    p.add_argument('--voxel',type=float,default=.1)
    p.add_argument('--range',type=float,default=90.)
    p.add_argument('--height',type=float,default=3.1)
    p.add_argument('--limit',type=int,default=0,help='Limit survey poses for a probe run')
    p.add_argument('--east-approach-x',type=float,help='Also survey the east access road up to this local x coordinate')
    p.add_argument('--road-bounds',type=float,nargs=4,metavar=('XMIN','YMIN','XMAX','YMAX'),
                   help='Also survey CARLA driving lanes in this local XY rectangle')
    p.add_argument('--plan-only',action='store_true')
    args=p.parse_args()
    if min(args.spacing,args.voxel,args.range,args.height)<=0:
        p.error('Spacing, voxel size, range and height must be positive')
    args.output_dir.mkdir(parents=True,exist_ok=True)
    output=args.output_dir/'pointcloud_map.pcd'
    if output.exists():
        p.error(f'Refusing to overwrite {output}')
    poses=survey_poses(args.lanelet,args.spacing)
    if args.east_approach_x is not None or args.road_bounds is not None:
        reference=carla.Map('survey-plan',args.opendrive.read_text())
        eastern_edge=poses[:,0].max()
        extra=[]
        for wp in reference.generate_waypoints(args.spacing):
            loc=wp.transform.location
            approach=args.east_approach_x is not None and eastern_edge < loc.x <= args.east_approach_x and -10 < -loc.y < 10
            bounds=args.road_bounds
            in_bounds=bounds is not None and bounds[0]<=loc.x<=bounds[2] and bounds[1]<=-loc.y<=bounds[3]
            if approach or in_bounds:
                if np.min(np.linalg.norm(poses[:,:2]-[loc.x,-loc.y],axis=1))<args.spacing*.75:continue
                extra.append([loc.x,-loc.y,loc.z,0])
        if not extra:raise ValueError('No driving-lane poses found for requested east approach')
        poses=np.concatenate([poses,np.asarray(sorted(extra))])
    if args.limit:poses=poses[:args.limit]
    np.savetxt(args.output_dir/'survey_poses.csv',poses,delimiter=',',header='local_x,local_y,road_z,lanelet_id',comments='')
    print(f'Survey planned: {len(poses)} positions, {len(poses)*2} full-rotation scans',flush=True)
    if args.plan_only:return
    client=carla.Client(args.host,args.port);client.set_timeout(120)
    world=client.get_world()
    # This tool is intended for a dedicated server: never reload one with live traffic.
    traffic=[a for a in world.get_actors() if a.type_id.startswith(('vehicle.','walker.','sensor.'))]
    if traffic:raise RuntimeError('Mapping server has live traffic or sensors; use a dedicated server')
    if world.get_map().name.split('/')[-1]!='UBAutonomousProvingGrounds':
        print('Loading UBAutonomousProvingGrounds...',flush=True)
        available=client.get_available_maps()
        matches=[name for name in available if name.split('/')[-1]=='UBAutonomousProvingGrounds']
        if len(matches)!=1:raise RuntimeError(f'Cannot uniquely identify UB map in {available}')
        world=client.load_world(matches[0])
    exported=world.get_map().to_opendrive()
    expected=args.opendrive.read_text()
    if hashlib.sha256(exported.encode()).digest()!=hashlib.sha256(expected.encode()).digest():
        if ET.canonicalize(exported,strip_text=True)!=ET.canonicalize(expected,strip_text=True):
            raise RuntimeError('Running map OpenDRIVE does not match the requested release')
    print('Verified running map matches supplied v1.1.0 OpenDRIVE',flush=True)
    original=world.get_settings()
    settings=world.get_settings();settings.synchronous_mode=True;settings.fixed_delta_seconds=.1
    settings.no_rendering_mode=True;settings.max_substeps=10;settings.max_substep_delta_time=.01
    sensor=None; q=queue.Queue(); cloud=np.empty((0,4),dtype='<f4');pending=[]
    labels=Counter(); excluded=sorted({int(getattr(carla.CityObjectLabel,n)) for n in DYNAMIC_NAMES if hasattr(carla.CityObjectLabel,n)})
    scan_count=0;raw_count=0;removed=0;discarded=0;start=time.time(); completed=False
    try:
        world.apply_settings(settings)
        bp=world.get_blueprint_library().find('sensor.lidar.ray_cast_semantic')
        attributes={'channels':'128','rotation_frequency':'10','points_per_second':'1310720',
                    'range':str(args.range),'upper_fov':'20','lower_fov':'-40','horizontal_fov':'360','sensor_tick':'0'}
        for k,v in attributes.items():bp.set_attribute(k,v)
        sensor=world.spawn_actor(bp,carla.Transform(carla.Location(x=float(poses[0,0]),y=-float(poses[0,1]),z=args.height)))
        sensor.listen(q.put)
        for index,pose in enumerate(poses):
            for phase in range(2):
                transform=carla.Transform(carla.Location(x=float(pose[0]),y=-float(pose[1]),z=float(pose[2])+args.height),
                                          carla.Rotation(pitch=phase*60/127/2,yaw=phase*360/1024/2))
                response=client.apply_batch_sync([carla.command.ApplyTransform(sensor.id,transform)],False)[0]
                if response.has_error():raise RuntimeError(response.error)
                for attempt in range(5):
                    frame=world.tick(120)
                    while True:
                        measurement=q.get(timeout=120)
                        if measurement.frame==frame:break
                        if measurement.frame>frame:raise RuntimeError('Unexpected concurrent world ticker')
                    actual=measurement.transform.location
                    error=max(abs(actual.x-transform.location.x),abs(actual.y-transform.location.y),abs(actual.z-transform.location.z))
                    rotation_error=max(abs(measurement.transform.rotation.pitch-transform.rotation.pitch),
                                       abs(measurement.transform.rotation.yaw-transform.rotation.yaw))
                    if error<=.02 and rotation_error<=.02:break
                    discarded+=1
                else:
                    raise RuntimeError(f'Sensor pose did not settle at position {index}: location error {error}, rotation error {rotation_error}')
                points,counts,dropped=measurement_points(measurement,excluded)
                if len(points)<1000:raise RuntimeError(f'Empty or sparse LiDAR scan at pose {index}')
                pending.append(reduce_cloud(points,args.voxel))
                labels.update(counts);raw_count+=sum(counts.values());removed+=dropped;scan_count+=1
            if (index+1)%25==0 or index==len(poses)-1:
                cloud=reduce_cloud(np.concatenate([cloud,*pending]),args.voxel);pending.clear()
                print(f'poses={index+1}/{len(poses)} scans={scan_count} voxels={len(cloud):,} elapsed={time.time()-start:.0f}s',flush=True)
            if (index+1)%100==0:
                np.save(args.output_dir/'checkpoint.npy',cloud)
        if len(cloud)<10000:raise RuntimeError('Survey produced too few points')
        write_pcd(output,cloud)
        completed=True
    finally:
        if sensor is not None:
            sensor.stop();sensor.destroy()
        world.apply_settings(original)
        if not completed and (len(cloud) or pending):
            if pending:cloud=reduce_cloud(np.concatenate([cloud,*pending]),args.voxel)
            np.save(args.output_dir/'partial.npy',cloud)
    manifest={'source_lanelet':str(args.lanelet),'lanelet_sha256':digest(args.lanelet),
              'source_opendrive':str(args.opendrive),'opendrive_sha256':digest(args.opendrive),
              'server_version':client.get_server_version(),'map':world.get_map().name,
              'survey_positions':len(poses),'scans':scan_count,'raw_returns':int(raw_count),
              'discarded_transition_scans':discarded,'east_approach_x':args.east_approach_x,'additional_road_bounds':args.road_bounds,
              'removed_dynamic_returns':removed,'excluded_semantic_labels':excluded,
              'observed_semantic_labels':{str(int(k)):int(v) for k,v in sorted(labels.items())},
              'points':len(cloud),'voxel_m':args.voxel,'pose_spacing_m':args.spacing,
              'sensor_height_m':args.height,'sensor_attributes':attributes,
              'scan_phases':[{'pitch':0,'yaw':0},{'pitch':60/127/2,'yaw':360/1024/2}],
              'bounds_min':cloud[:,:3].min(axis=0).tolist(),'bounds_max':cloud[:,:3].max(axis=0).tolist(),
              'coordinate_transform':'measurement.transform matrix, then world_y *= -1; no recentering',
              'intensity':'synthetic exp(-0.004 * range_m), matching default CARLA RayCastLidar attenuation',
              'voxel_representative':'first actual static return in each 0.1m voxel',
              'elapsed_seconds':time.time()-start,'pcd_sha256':digest(output),'pcd_bytes':output.stat().st_size}
    (args.output_dir/'capture.json').write_text(json.dumps(manifest,indent=2)+'\n')
    checkpoint=args.output_dir/'checkpoint.npy'
    if checkpoint.exists():checkpoint.unlink()
    print(f'Wrote {output}: {len(cloud):,} points',flush=True)


if __name__=='__main__':main()
