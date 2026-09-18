"""Independent artifact checks. Unavailable validation is never a pass."""
import json
import math
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial import cKDTree
import yaml
from .common import sha256, write_json
from .cloud import read_pcd


def tags(e): return {x.get('k'):x.get('v') for x in e.findall('tag')}


def native_routing(path):
    """Exercise installed Lanelet2 IO and routing, using temporary geographic tags.

    Vanilla Lanelet2 has no Autoware Local projector. Temporary UTM coordinates
    preserve orientation during IO; afterwards restore exact Local XYZ tags.
    This is explicitly distinct from an Autoware loader execution.
    """
    try:
        import lanelet2
        from pyproj import Transformer
    except ImportError as ex: return dict(status='untested',reason=str(ex))
    root=ET.parse(path).getroot(); transform=Transformer.from_crs(32631,4326,always_xy=True)
    for n in root.findall('node'):
        t=tags(n); lon,lat=transform.transform(float(t['local_x'])+500000,float(t['local_y']))
        n.set('lat',str(lat)); n.set('lon',str(lon))
    with tempfile.TemporaryDirectory(prefix='carla-lanelet-') as d:
        p=Path(d)/'map.osm'; ET.ElementTree(root).write(p)
        projector=lanelet2.projection.UtmProjector(lanelet2.io.Origin(0,3))
        m,errors=lanelet2.io.loadRobust(str(p),projector)
        for point in m.pointLayer:
            point.x=float(point.attributes['local_x']); point.y=float(point.attributes['local_y'])
        rules=lanelet2.traffic_rules.create(lanelet2.traffic_rules.Locations.Germany,lanelet2.traffic_rules.Participants.Vehicle)
        graph=lanelet2.routing.RoutingGraph(m,rules)
        graph_errors=list(graph.checkValidity(False))
        edges=sorted([l.id,n.id] for l in m.laneletLayer for n in graph.following(l,False))
        changes=sorted([l.id,n.id] for l in m.laneletLayer for n in graph.following(l,True) if n.id not in {x.id for x in graph.following(l,False)})
        return dict(status='passed' if not errors and not graph_errors else 'failed',load_errors=list(errors),graph_errors=graph_errors,
                    edges=edges,lane_changes=changes,lanelets=len(m.laneletLayer),traffic_rules='Germany/Vehicle (routing mechanics only)')


def validate(directory,network=None):
    directory=Path(directory)
    summary=json.loads((directory/'network.json').read_text())
    config=json.loads((directory/'config.json').read_text())
    mapping=json.loads((directory/'id_mapping.json').read_text()) if (directory/'id_mapping.json').exists() else None
    diagnostics=summary['diagnostics']
    errors=[x for x in diagnostics if x['category']=='structural' and x['severity']=='error']
    report=dict(source_fingerprint=summary['source_fingerprint'],structural=dict(status='untested'),coverage=dict(status='untested',reason='No exported capture'),
                regulatory=dict(status='failed' if any(x['category']=='regulatory' and x['severity']=='error' for x in diagnostics) else 'passed'),
                runtime={k:dict(status='untested',reason='Scenario has not been executed for these artifacts') for k in ('live_capture','autoware_loader','autoware_routing','controlled_ndt','traffic_light_planning','stop_line_planning')},
                diagnostics=diagnostics)
    path=directory/'lanelet2_map.osm'; lines=[]
    if path.exists():
        root=ET.parse(path).getroot(); nodes={}; ways={}; relations={}; seen=set()
        for e in root:
            if e.get('id') is not None:
                if e.get('id') in seen: errors.append(dict(code='duplicate_id',source=e.get('id')))
                seen.add(e.get('id'))
        for n in root.findall('node'):
            t=tags(n)
            try: p=np.array([float(t[k]) for k in ('local_x','local_y','ele')])
            except (ValueError,KeyError): errors.append(dict(code='invalid_local_node',source=n.get('id'))); continue
            if not np.isfinite(p).all(): errors.append(dict(code='nonfinite_node',source=n.get('id')))
            nodes[n.get('id')]=p
        for w in root.findall('way'):
            refs=[n.get('ref') for n in w.findall('nd')]
            if len(refs)<2 or any(r not in nodes for r in refs): errors.append(dict(code='invalid_way',source=w.get('id'))); continue
            ways[w.get('id')]=refs
        for r in root.findall('relation'):
            relations[r.get('id')]=r
        primitive={'node':nodes,'way':ways,'relation':relations}
        for r in relations.values():
            for m in r.findall('member'):
                if m.get('ref') not in primitive.get(m.get('type'),{}): errors.append(dict(code='dangling_member',source=r.get('id')))
        endpoints={}
        polygon_status='passed'
        try: from shapely.geometry import Polygon
        except ImportError: Polygon=None; polygon_status='untested'
        for r in relations.values():
            if tags(r).get('type')!='lanelet': continue
            members={m.get('role'):m.get('ref') for m in r.findall('member')}
            if any(members.get(k) not in ways for k in ('left','right')): errors.append(dict(code='lane_boundaries',source=r.get('id'))); continue
            lr,rr=[ways[members[k]] for k in ('left','right')]
            left,right=[np.array([nodes[n] for n in refs]) for refs in (lr,rr)]
            if np.linalg.norm(left[0]-right[-1])+np.linalg.norm(left[-1]-right[0]) < np.linalg.norm(left[0]-right[0])+np.linalg.norm(left[-1]-right[-1]): right=right[::-1]; rr=rr[::-1]
            # Align both boundaries to the declared left/right relationship.
            direction=left[1]-left[0]; across=right[0]-left[0]
            if direction[0]*across[1]-direction[1]*across[0]>0: left=left[::-1];right=right[::-1];lr=lr[::-1];rr=rr[::-1]
            endpoints[int(r.get('id'))]=[lr[0],rr[0],lr[-1],rr[-1]]
            for p in (left,right):
                lines.append(p)
                if np.linalg.norm(np.diff(p,axis=0),axis=1).max()>config['max_spacing']+2*config['join_tolerance']+1e-6 and tags(r).get('subtype')=='road': errors.append(dict(code='boundary_spacing',source=r.get('id')))
            if Polygon:
                polygon=Polygon(np.vstack([left[:,:2],right[::-1,:2]]))
                if not polygon.is_valid or polygon.area<1e-6: errors.append(dict(code='invalid_lane_polygon',source=r.get('id')))
        expected=[]
        if mapping:
            for a,b in summary['expected_edges']:
                ia,ib=mapping['lanes'][a],mapping['lanes'][b]; expected.append([ia,ib])
                if ia not in endpoints or ib not in endpoints or endpoints[ia][2:]!=endpoints[ib][:2]: errors.append(dict(code='missing_routing_edge',source=a,target=b))
        native=native_routing(path)
        if native['status']!='untested':
            missing=sorted(set(map(tuple,expected))-set(map(tuple,native['edges'])))
            unexpected=sorted(set(map(tuple,native['edges']))-set(map(tuple,expected)))
            native.update(missing_edges=missing,unexpected_edges=unexpected)
            if missing or unexpected: native['status']='failed'
        report['structural']=dict(status='failed' if errors or native['status']=='failed' else 'untested' if polygon_status=='untested' or native['status']=='untested' else 'passed',
                                  errors=errors,polygon_check=polygon_status,lanelet2=native,nodes=len(nodes),ways=len(ways),lanelets=len(endpoints))
        report['artifact_hashes']={'lanelet2_map.osm':sha256(path),'map_projector_info.yaml':sha256(directory/'map_projector_info.yaml')}
        if yaml.safe_load((directory/'map_projector_info.yaml').read_text())!={'projector_type':'Local'}:
            report['structural']['status']='failed'; errors.append(dict(code='projector_mismatch',source='map_projector_info.yaml'))
    elif errors:
        report['structural']=dict(status='failed',errors=errors)
    cap_path=directory/'capture.json'
    if cap_path.exists():
        cap=json.loads(cap_path.read_text())
        report['runtime'].update(cap.get('runtime_checks',{}))
        files=cap.get('files',[])
        report.setdefault('artifact_hashes', {})['capture.json'] = sha256(cap_path)
        if (directory/'pointcloud_map_metadata.yaml').exists():
            report['artifact_hashes']['pointcloud_map_metadata.yaml'] = sha256(directory/'pointcloud_map_metadata.yaml')
        coverage_errors=[]; total=0
        stations=json.loads((directory/'stations.json').read_text())
        xyz=np.array([s['xyz'] for s in stations]).reshape(-1,3)
        distances=np.full(len(xyz),np.inf)
        metadata=yaml.safe_load((directory/'pointcloud_map_metadata.yaml').read_text()) if (directory/'pointcloud_map_metadata.yaml').exists() else None
        if cap['identity']['source_fingerprint']!=summary['source_fingerprint']: coverage_errors.append('Capture source differs from lane network')
        for item in files:
            p=directory/item['path']
            report['artifact_hashes'][item['path']] = sha256(p)
            if report['artifact_hashes'][item['path']]!=item['sha256']: coverage_errors.append(f'PCD hash mismatch: {p.name}')
            cloud=read_pcd(p); total+=len(cloud)
            if len(cloud)!=item['points']: coverage_errors.append(f'PCD count mismatch: {p.name}')
            for start in range(0,len(cloud),100000):
                points=np.asarray(cloud[start:start+100000])
                if not np.isfinite(points).all() or np.any((points[:,3]<0)|(points[:,3]>1)):
                    coverage_errors.append(f'Invalid points/intensity: {p.name}'); continue
                if metadata is not None:
                    low=metadata.get(p.name)
                    if low is None: coverage_errors.append(f'Missing tile metadata: {p.name}')
                    elif np.any(points[:,:2]<low) or np.any(points[:,:2]>=np.array(low)+[metadata['x_resolution'],metadata['y_resolution']]): coverage_errors.append(f'Points outside tile: {p.name}')
                if len(xyz) and len(points): distances=np.minimum(distances,cKDTree(points[:,:3]).query(xyz,workers=1)[0])
        fraction=float(np.mean(distances<=config['surface_tolerance'])) if len(xyz) else 0.
        complete=cap.get('status')=='complete' and cap.get('completed_stations')==len(stations)
        if total != cap.get('points'): coverage_errors.append('Exported point count does not match capture')
        if not complete: coverage_errors.append('Capture incomplete')
        if not files or total==0: coverage_errors.append('No exported points')
        if fraction<config['coverage_fraction']: coverage_errors.append('Insufficient 3D road-surface coverage')
        report['coverage']=dict(status='failed' if coverage_errors else 'passed',errors=coverage_errors,points=total,stations=len(xyz),
                                surface_tolerance_m=config['surface_tolerance'],fraction=fraction,max_distance_m=float(distances.max()) if len(distances) and np.isfinite(distances).all() else None,
                                missing_station_ids=[s['id'] for s,d in zip(stations,distances) if d>config['surface_tolerance']])
    evidence=directory/'runtime_validation.json'
    if evidence.exists():
        runtime=json.loads(evidence.read_text())
        if runtime.get('source_fingerprint')==summary['source_fingerprint'] and runtime.get('artifact_hashes')==report.get('artifact_hashes'):
            report['runtime'].update(runtime.get('checks',{}))
        else: report['runtime']['evidence']=dict(status='failed',reason='Runtime evidence does not match current source/artifacts')
    report['ready']=all(report[k]['status']=='passed' for k in ('structural','coverage','regulatory')) and all(v['status']=='passed' for v in report['runtime'].values())
    write_json(directory/'validation.json',report)
    preview(directory,lines,summary,report)
    return report


def preview(directory,lines,summary,report):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.collections import LineCollection
    except ImportError: return
    fig,axes=plt.subplots(1,2,figsize=(14,6))
    for ax,indices,title in [(axes[0],[0,1],'Local XY'),(axes[1],[0,2],'Local X / elevation')]:
        if lines: ax.add_collection(LineCollection([p[:,indices] for p in lines],linewidths=.35))
        ax.autoscale();ax.set_aspect('equal',adjustable='datalim');ax.set_title(title);ax.set_xlabel('x (m)')
    axes[0].set_ylabel('y (m)');axes[1].set_ylabel('z (m)')
    fig.suptitle(f'{summary["lanes"]} driving segments | {len(summary["components"])} components | ready={report["ready"]}')
    fig.tight_layout(); fig.savefig(Path(directory)/'validation.png',dpi=130);plt.close(fig)
