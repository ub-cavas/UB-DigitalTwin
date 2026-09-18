#!/usr/bin/env python3
"""Run installed Autoware loaders in an isolated ROS domain.

Execute inside the sourced Autoware environment. This test requires no driving
stack and never publishes into the application's normal ROS domain. It records
NDT and planning scenarios as untested; loading a map cannot verify those.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time

p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('--domain',type=int,default=187);p.add_argument('--timeout',type=float,default=45);args=p.parse_args()
if not 1<=args.domain<=232: p.error('Use an explicit isolated ROS domain from 1 to 232')
os.environ['ROS_DOMAIN_ID']=str(args.domain)
os.environ['ROS_LOCALHOST_ONLY']='1'
os.environ.pop('CYCLONEDDS_URI', None)
import rclpy
from rclpy.qos import QoSProfile,DurabilityPolicy,ReliabilityPolicy
from sensor_msgs.msg import PointCloud2
from autoware_map_msgs.msg import LaneletMapBin,MapProjectorInfo

run=args.run.resolve();validation=json.loads((run/'validation.json').read_text());processes=[];logs=[];received={}
commands=[
 ['ros2','run','autoware_map_projection_loader','autoware_map_projection_loader_node','--ros-args','-p',f'map_projector_info_path:={run}/map_projector_info.yaml','-p',f'lanelet2_map_path:={run}/lanelet2_map.osm'],
 ['ros2','run','autoware_map_loader','autoware_lanelet2_map_loader','--ros-args','-p',f'lanelet2_map_path:={run}/lanelet2_map.osm','-p','center_line_resolution:=1.0','-p','allow_unsupported_version:=true','-p','use_waypoints:=true','-r','output/lanelet2_map:=/mapping_probe/vector_map'],
 ['ros2','run','autoware_map_loader','autoware_pointcloud_map_loader','--ros-args','-p',f'pcd_paths_or_directory:=[{run}/pointcloud_map.pcd]','-p',f'pcd_metadata_path:={run}/pointcloud_map_metadata.yaml','-p','enable_whole_load:=true','-p','enable_downsampled_whole_load:=false','-p','enable_partial_load:=true','-p','enable_selected_load:=false','-p','leaf_size:=0.1','-r','output/pointcloud_map:=/mapping_probe/pointcloud_map'],
]
checks={k:dict(status='untested',reason='No controlled driving/localization scenario with ground truth available in this loader-only test') for k in ('controlled_ndt','traffic_light_planning','stop_line_planning')}
rclpy.init();node=rclpy.create_node('mapping_artifact_probe');qos=QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL,reliability=ReliabilityPolicy.RELIABLE)
subscriptions=[]
for typ,topic,key in [(LaneletMapBin,'/mapping_probe/vector_map','lanelet'),(PointCloud2,'/mapping_probe/pointcloud_map','pointcloud'),(MapProjectorInfo,'/map/map_projector_info','projector')]:
    subscriptions.append(node.create_subscription(typ,topic,lambda msg,key=key:received.__setitem__(key,msg),qos))
try:
    for i,command in enumerate(commands):
        log=(run/f'runtime-loader-{i}.log').open('w');logs.append(log)
        processes.append(subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True))
    deadline=time.monotonic()+args.timeout
    while time.monotonic()<deadline and len(received)<3:
        rclpy.spin_once(node,timeout_sec=.2)
        if any(p.poll() is not None for p in processes): break
    expected=json.loads((run/'capture.json').read_text()).get('points')
    count=received['pointcloud'].width*received['pointcloud'].height if 'pointcloud' in received else None
    checks['autoware_loader']=dict(status='passed' if len(received)==3 and len(received['lanelet'].data)>0 and count==expected and received['projector'].projector_type=='Local' else 'failed',
                                  received=sorted(received),pointcloud_points=count,expected_points=expected,domain=args.domain,
                                  commands=commands,logs=[f'runtime-loader-{i}.log' for i in range(len(commands))])
    # Autoware registers its additional rules/parsers when importing this module.
    try:
        import lanelet2
        import autoware_lanelet2_extension_python.regulatory_elements
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        from carla_mapping.validation import native_routing
        result=native_routing(run/'lanelet2_map.osm')
        summary=json.loads((run/'network.json').read_text());mapping=json.loads((run/'id_mapping.json').read_text())
        expected_edges={tuple(mapping['lanes'][k] for k in edge) for edge in summary['expected_edges']}
        actual=set(map(tuple,result.get('edges',[])))
        checks['autoware_routing']=dict(status=('passed' if actual==expected_edges else 'failed') if result['status']=='passed' and expected_edges else 'untested',
                                       expected_edges=len(expected_edges),actual_edges=len(actual),missing_edges=sorted(expected_edges-actual),unexpected_edges=sorted(actual-expected_edges),
                                       note='Installed Lanelet2 with Autoware regulatory extensions; graph mechanics, not route driving')
    except Exception as ex: checks['autoware_routing']=dict(status='untested',reason=str(ex))
finally:
    for process in processes:
        if process.poll() is None: os.killpg(process.pid,signal.SIGINT)
    for process in processes:
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: os.killpg(process.pid,signal.SIGKILL);process.wait()
    for log in logs:log.close()
    node.destroy_node();rclpy.shutdown()
report=dict(source_fingerprint=validation['source_fingerprint'],artifact_hashes=validation.get('artifact_hashes'),checks=checks)
(run/'runtime_validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(checks,indent=2))
raise SystemExit(0 if checks['autoware_loader']['status']=='passed' else 1)
