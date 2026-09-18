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
    """Compatibility CLI using the transactional collector."""
    import sys
    from scipy.spatial import cKDTree
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from carla_mapping.common import configuration, atomic_write, write_json
    from carla_mapping.network import Network
    from carla_mapping.capture import connect, capture
    from carla_mapping.validation import validate
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host', default='127.0.0.1'); p.add_argument('--port', type=int, default=2100)
    p.add_argument('--map'); p.add_argument('--lanelet', type=Path)
    p.add_argument('--opendrive', type=Path, required=True); p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--spacing', type=float, default=3.); p.add_argument('--voxel', type=float, default=.1)
    p.add_argument('--range', type=float, default=90.); p.add_argument('--height', type=float, default=3.1)
    p.add_argument('--limit', type=int, default=0); p.add_argument('--road-bounds', type=float, nargs=4)
    p.add_argument('--east-approach-x', type=float); p.add_argument('--plan-only', action='store_true')
    p.add_argument('--resume', action='store_true'); p.add_argument('--config', type=Path)
    args = p.parse_args()
    config = configuration(args.config, dict(station_spacing=args.spacing, voxel=args.voxel, range=args.range, height=args.height, export='single'))
    network = Network(args.opendrive.read_text(), config)
    stations = network.stations()
    if args.lanelet:
        poses = survey_poses(args.lanelet, args.spacing)
        if not stations: raise ValueError('No OpenDRIVE driving network')
        reference = np.array([s['xyz'] for s in stations])
        _, nearest = cKDTree(reference).query(poses[:, :3])
        prefix = digest(args.lanelet)
        authored = [dict(stations[int(index)], id=f'authored/{prefix}/station/{i}', xyz=pose[:3].tolist(), lane=f'authored/{int(pose[3])}')
                    for i, (pose, index) in enumerate(zip(poses, nearest))]
        eastern_edge = poses[:, 0].max()
        bounds = args.road_bounds
        additional = [s for s in stations if
                      (bounds and bounds[0] <= s['xyz'][0] <= bounds[2] and bounds[1] <= s['xyz'][1] <= bounds[3]) or
                      (args.east_approach_x is not None and eastern_edge < s['xyz'][0] <= args.east_approach_x and -10 < s['xyz'][1] < 10)]
        stations = authored + additional
    elif args.road_bounds:
        b = args.road_bounds
        stations = [s for s in stations if b[0] <= s['xyz'][0] <= b[2] and b[1] <= s['xyz'][1] <= b[3]]
    elif args.east_approach_x is not None:
        p.error('--east-approach-x requires --lanelet; prefer map.py pcd --bounds')
    # Reuse the same installed-map protection and exclusive run lock as map.py.
    import importlib.util
    spec = importlib.util.spec_from_file_location('mapping_cli', Path(__file__).resolve().parents[1] / 'map.py')
    cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
    directory = args.output_dir
    repo = Path(__file__).resolve().parents[2]
    if any(protected.resolve() == directory.resolve() or protected.resolve() in directory.resolve().parents
           for protected in (repo / 'Autoware/host_data/maps', repo / 'Autoware/maps')):
        p.error('Use a separate run directory outside installed maps')
    with cli.run_lock(directory):
        if (directory / 'capture/capture.sqlite3').exists() and not args.resume:
            p.error('Capture exists; use --resume')
        if (directory / 'source.xodr').exists():
            if (directory / 'source.xodr').read_text() != network.source or json.loads((directory / 'stations.json').read_text()) != stations or json.loads((directory / 'config.json').read_text()) != config:
                p.error('Existing run is incompatible with this survey')
        elif any(x.name != '.lock' for x in directory.iterdir()):
            p.error('Output directory must be empty')
        atomic_write(directory / 'source.xodr', network.source)
        write_json(directory / 'config.json', config); write_json(directory / 'stations.json', stations)
        write_json(directory / 'network.json', network.summary())
        np.savetxt(directory / 'survey_poses.csv', np.asarray([s['xyz'] for s in stations]), delimiter=',', header='x,y,z')
        if args.plan_only:
            print(f'Planned {len(stations)} stations in {directory}'); return
        client, world = connect(args.host, args.port, args.map)
        capture(client, world, network, stations, directory, args.resume, args.limit or None)
        report = validate(directory)
        print(f'Wrote {directory / "pointcloud_map.pcd"}; coverage: {report["coverage"]["status"]}')


if __name__ == '__main__':
    main()
