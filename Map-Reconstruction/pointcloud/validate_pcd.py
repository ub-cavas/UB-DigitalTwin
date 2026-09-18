#!/usr/bin/env python3
"""Validate a generated XYZI PCD and visualize coverage against a Lanelet map."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from scipy.spatial import cKDTree

from remap_carla import digest, survey_poses, voxel_keys


def load_pcd(path):
    fields={}
    with path.open('rb') as f:
        while True:
            line=f.readline()
            if not line:raise ValueError('Missing PCD DATA header')
            parts=line.decode('ascii').strip().split()
            if parts and not parts[0].startswith('#'):fields[parts[0]]=parts[1:]
            if parts[:1]==['DATA']:break
        offset=f.tell()
    expected={'FIELDS':['x','y','z','intensity'],'SIZE':['4']*4,'TYPE':['F']*4,
              'COUNT':['1']*4,'HEIGHT':['1'],'DATA':['binary']}
    for key,value in expected.items():
        if fields.get(key)!=value:raise ValueError(f'Unsupported PCD {key}: {fields.get(key)}')
    count=int(fields['POINTS'][0])
    if int(fields['WIDTH'][0])!=count:raise ValueError('WIDTH and POINTS disagree')
    if path.stat().st_size-offset!=count*16:raise ValueError('PCD payload length does not match header')
    return np.memmap(path,mode='r',dtype='<f4',offset=offset,shape=(count,4))


def stats(points):
    return {'points':len(points),'bounds_min':points[:,:3].min(axis=0).tolist(),
            'bounds_max':points[:,:3].max(axis=0).tolist(),
            'above_1m_points':int((points[:,2]>1).sum()),
            'ground_z_percentiles':np.percentile(points[(points[:,2]>-.25)&(points[:,2]<.3),2],[1,50,99]).tolist()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--previous',type=Path)
    parser.add_argument('--lanelet',type=Path)
    parser.add_argument('--capture',type=Path,required=True)
    parser.add_argument('--report-dir',type=Path,required=True)
    args=parser.parse_args()
    args.report_dir.mkdir(parents=True,exist_ok=True)
    manifest=json.loads(args.capture.read_text())
    if 'identity' in manifest:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from carla_mapping.validation import validate
        if args.candidate.resolve() != (args.capture.parent / 'pointcloud_map.pcd').resolve():
            parser.error('Candidate must be the PCD referenced by this capture run')
        report = validate(args.capture.parent)
        result = dict(report['coverage'], passed=report['coverage']['status'] == 'passed')
        (args.report_dir / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, indent=2))
        if not result['passed']: raise SystemExit(1)
        return
    if args.previous is None or args.lanelet is None:
        parser.error('Historical capture manifests require --previous and --lanelet; new manifests do not')
    candidate=load_pcd(args.candidate);previous=load_pcd(args.previous)
    problems=[]
    if not np.isfinite(candidate).all():problems.append('Non-finite PCD values')
    if not ((candidate[:,3]>=0)&(candidate[:,3]<=1)).all():problems.append('Intensity outside [0,1]')
    unique=len(np.unique(voxel_keys(candidate,manifest['voxel_m'])))
    if unique!=len(candidate):problems.append('Duplicate output voxels')
    if digest(args.candidate)!=manifest['pcd_sha256']:problems.append('Capture/PCD checksum mismatch')
    if digest(args.lanelet)!=manifest['lanelet_sha256']:problems.append('Lanelet changed since capture')
    if manifest['scans']!=2*manifest['survey_positions']:problems.append('Incomplete survey')
    if len(candidate)<1000000:problems.append('Unexpectedly sparse proving-ground map')
    samples=survey_poses(args.lanelet,1.0)
    ground=candidate[(candidate[:,2]>-.25)&(candidate[:,2]<.3),:2]
    # Retain occupied 20 cm ground cells to bound memory for the coverage query.
    grid=np.floor(ground/.2).astype(np.int64)
    keys=(grid[:,0]+100000)*200000+(grid[:,1]+100000)
    _,indices=np.unique(keys,return_index=True)
    tree=cKDTree(ground[indices]);distance,_=tree.query(samples[:,:2])
    coverage=float((distance<=.5).mean())
    if coverage<.99:problems.append(f'Only {coverage:.1%} of Lanelet center samples have nearby ground returns')
    survey=np.loadtxt(args.capture.parent/'survey_poses.csv',delimiter=',',skiprows=1,ndmin=2)
    survey_distance,_=tree.query(survey[:,:2])
    survey_coverage=float((survey_distance<=.5).mean())
    if survey_coverage<.99:problems.append(f'Only {survey_coverage:.1%} of survey stations have nearby ground returns')
    report={'passed':not problems,'problems':problems,'candidate':stats(candidate),'previous':stats(previous),
            'pcd_sha256':manifest['pcd_sha256'],'previous_sha256':digest(args.previous),
            'finite_values':bool(np.isfinite(candidate).all()),'unique_voxels':unique,
            'lanelet_ground_coverage':{'samples':len(samples),'within_0_5m_fraction':coverage,
                                       'nearest_return_distance_percentiles_m':np.percentile(distance,[50,95,99,100]).tolist()},
            'survey_station_ground_coverage':{'samples':len(survey),'within_0_5m_fraction':survey_coverage,
                                              'max_nearest_return_distance_m':float(survey_distance.max())},
            'limitations':['Synthetic static CARLA survey, not a physical LiDAR capture.',
                           'Intensity is modeled range attenuation, not calibrated reflectance.',
                           'Autoware NDT localization has not been driven end to end.']}
    (args.report_dir/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
    fig,axes=plt.subplots(2,1,figsize=(14,10),facecolor='#f8fafb',sharex=True,sharey=True)
    for ax,points,title in zip(axes,[previous,candidate],['Previous installed PCD','Fresh v1.1.0 static LiDAR survey']):
        stride=max(1,len(points)//450000)
        sample=points[::stride]
        ax.scatter(sample[:,0],sample[:,1],c=np.clip(sample[:,2],0,10),s=.12,cmap='viridis',vmin=0,vmax=10,rasterized=True)
        ax.set_title(title,loc='left',fontsize=14);ax.set_aspect('equal');ax.set_facecolor('#ecf0f2')
        ax.set_ylabel('Local y (m)');ax.grid(alpha=.15)
    r=ET.parse(args.lanelet).getroot()
    nodes={n.get('id'):{t.get('k'):t.get('v') for t in n.findall('tag')} for n in r.findall('node')}
    boundary_ids={m.get('ref') for rel in r.findall('relation') for m in rel.findall('member') if m.get('role') in ('left','right')}
    for way in r.findall('way'):
        if way.get('id') not in boundary_ids:continue
        p=np.array([[float(nodes[n.get('ref')]['local_x']),float(nodes[n.get('ref')]['local_y'])] for n in way.findall('nd')])
        axes[1].plot(p[:,0],p[:,1],color='#ff833e',lw=.5,alpha=.8)
    axes[1].set_xlabel('Local x (m)')
    fig.suptitle('UB v1.1.0 • Point-cloud remapping',fontsize=20,x=.08,ha='left')
    fig.text(.08,.025,f"{len(candidate):,} points • {manifest['voxel_m']:.2f} m voxels • {manifest['scans']:,} scans • {coverage:.1%} Lanelet ground coverage within 0.5 m",fontsize=11)
    fig.subplots_adjust(left=.08,right=.97,bottom=.08,top=.92,hspace=.2)
    fig.savefig(args.report_dir/'comparison.png',dpi=150);plt.close(fig)
    print(json.dumps(report,indent=2))
    if problems:raise SystemExit(1)


if __name__=='__main__':main()
