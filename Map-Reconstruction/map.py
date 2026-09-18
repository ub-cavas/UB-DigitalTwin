#!/usr/bin/env python3
"""General-purpose CARLA 0.9.16 → Autoware Local mapping commands."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import shutil
import subprocess
import sys

from carla_mapping.common import atomic_write, configuration, fingerprint, write_json
from carla_mapping.network import Network


@contextmanager
def run_lock(directory):
    directory.mkdir(parents=True,exist_ok=True)
    with (directory/'.lock').open('a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('Another mapping process owns this run directory') from None
        yield


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    for name in ('inspect','build','lanelet','pcd','refit','validate'):
        s=sub.add_parser(name)
        s.add_argument('--host',default='127.0.0.1');s.add_argument('--port',type=int,default=2100)
        s.add_argument('--map',help='Explicit advertised CARLA map name; otherwise retain the loaded map')
        s.add_argument('--opendrive',type=Path,help='Offline source, or expected source for live capture')
        s.add_argument('--output-dir',type=Path,help='Fresh run directory; defaults to output/<timestamp>')
        s.add_argument('--config',type=Path);s.add_argument('--corrections',type=Path)
        s.add_argument('--bounds',type=float,nargs=4,metavar=('XMIN','YMIN','XMAX','YMAX'))
        s.add_argument('--source',type=Path,help='Authored Lanelet input for refit')
        if name in ('build','pcd'):
            s.add_argument('--plan-only',action='store_true');s.add_argument('--resume',action='store_true')
            s.add_argument('--limit',type=int,help='Capture at most this many new stations; result stays partial')
            s.add_argument('--export',choices=('single','tiled'))
        if name in ('inspect','lanelet'):
            s.add_argument('--live',action='store_true',help='Collect CARLA topology and runtime control evidence')
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    from carla_mapping.validation import validate
    if args.command=='validate':
        if args.output_dir is None: raise ValueError('validate requires --output-dir for an existing run')
        with run_lock(args.output_dir):
            report=validate(args.output_dir)
        print(json.dumps({k:report[k] for k in ('ready','regulatory','coverage')},indent=2))
        return 0 if report['ready'] else 2
    if getattr(args,'limit',None) is not None and args.limit<=0: raise ValueError('--limit must be positive')
    if args.command=='refit':
        if args.source is None or args.opendrive is None: raise ValueError('refit requires --source and --opendrive')
    config=configuration(args.config,dict(bounds=args.bounds,export=getattr(args,'export',None)))
    directory=args.output_dir or Path(__file__).resolve().parent/'output'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    # A run may never be an installed-map directory, even if initially empty.
    repo=Path(__file__).resolve().parent.parent
    resolved=directory.resolve()
    for protected in (repo/'Autoware/host_data/maps',repo/'Autoware/maps'):
        if resolved==protected.resolve() or protected.resolve() in resolved.parents:
            raise ValueError('Use a separate run directory outside installed maps and published map artifacts')
    resume=getattr(args,'resume',False)
    existing=(directory/'source.xodr').exists()
    if existing and not resume:
        raise ValueError('Run already exists; choose a fresh output directory or --resume for capture')
    live=(args.command in ('build','pcd') and not args.plan_only) or getattr(args,'live',False) or args.opendrive is None
    client=world=None
    if live:
        from carla_mapping.capture import connect
        client,world=connect(args.host,args.port,args.map)
        source=world.get_map().to_opendrive()
        if args.opendrive and fingerprint(args.opendrive.read_text())!=fingerprint(source): raise ValueError('Selected server map does not match --opendrive')
    else:
        if args.map: raise ValueError('--map requires live mode; use --live or omit --plan-only')
        source=args.opendrive.read_text()
    with run_lock(directory):
        if resume:
            if not existing: raise ValueError('No source snapshot found for --resume')
            if fingerprint((directory/'source.xodr').read_text())!=fingerprint(source): raise ValueError('Resume source fingerprint mismatch')
            old_config=json.loads((directory/'config.json').read_text())
            if args.config is None:
                # Default CLI values must not silently change an existing run.
                config=old_config.copy()
                for k,v in dict(bounds=args.bounds,export=getattr(args,'export',None)).items():
                    if v is not None and v!=config[k]: raise ValueError(f'Incompatible resume option: {k}')
            elif old_config!=config: raise ValueError('Resume configuration mismatch')
            if args.corrections is None and (directory/'corrections.yaml').exists(): args.corrections=directory/'corrections.yaml'
        else:
            if any(p.name!='.lock' for p in directory.iterdir()): raise ValueError('Output directory must be empty')
            atomic_write(directory/'source.xodr',source)
            write_json(directory/'config.json',config)
        network=Network(source,config)
        if world is not None:
            from carla_mapping.capture import runtime_evidence
            evidence=runtime_evidence(world,network)
            write_json(directory/'runtime_source.json',evidence)
        if args.corrections:
            network.corrections(args.corrections)

        stations=network.stations()
        if resume and json.loads((directory/'stations.json').read_text())!=stations: raise ValueError('Resume station plan changed')
        if resume:
            import sqlite3
            checkpoint = directory/'capture/capture.sqlite3'
            if not checkpoint.exists(): raise ValueError('No committed capture exists for --resume')
            with sqlite3.connect(f'file:{checkpoint}?mode=ro', uri=True) as db:
                identity = json.loads(db.execute('SELECT value FROM metadata WHERE key="identity"').fetchone()[0])
            if identity['correction_hash'] != network.correction_hash or identity['config'] != config:
                raise ValueError('Resume corrections/configuration differ from checkpoint; create a new run')
        if args.corrections and args.corrections.resolve()!=(directory/'corrections.yaml').resolve(): atomic_write(directory/'corrections.yaml',args.corrections.read_bytes())
        write_json(directory/'stations.json',stations)
        atomic_write(directory/'survey_poses.csv','station_id,lane_id,x,y,z,yaw,pitch,roll\n'+''.join(f'{s["id"]},{s["lane"]},'+','.join(str(x) for x in s['xyz']+[s['yaw'],s['pitch'],s['roll']])+'\n' for s in stations))
        if args.command in ('build','lanelet'):
            from carla_mapping.lanelet import Writer
            Writer(network).write(directory)
        elif args.command=='refit':
            legacy=Path(__file__).resolve().parent/'lanelet/refit_lanelet.py'
            subprocess.run([sys.executable,str(legacy),'--source',str(args.source),'--opendrive',str(args.opendrive),'--output',str(directory/'lanelet2_map.osm'),'--spacing',str(config['max_spacing'])],check=True)
            atomic_write(directory/'map_projector_info.yaml','projector_type: Local\n')
            network.diagnostics.add('legacy_refit_review','refit','Legacy authored-map refit uses geometric correspondence and planar synthesized turns; inspect its correspondence report before release')
        write_json(directory/'network.json',network.summary())
        if args.command in ('build','pcd') and not args.plan_only:
            if not stations: raise ValueError('No survey stations in selected road network')
            from carla_mapping.capture import capture
            capture(client,world,network,stations,directory,resume,getattr(args,'limit',None))
        if args.command!='inspect':
            report=validate(directory,network)
            print(f'Run: {directory}\nReady: {report["ready"]}. Review validation.json and validation.png.')
        else:
            summary=network.summary()
            print(json.dumps({k:summary[k] for k in ('source_fingerprint','roads','lanes')},indent=2))
            print(f'{len(summary["components"])} components; {len(stations)} stations; artifacts: {directory}')
    return 0


if __name__=='__main__':
    try: sys.exit(main())
    except KeyboardInterrupt:
        print('Interrupted. Completed stations are checkpointed; rerun with --resume.',file=sys.stderr);sys.exit(130)
    except (ValueError,RuntimeError,OSError) as ex:
        print(f'Error: {ex}',file=sys.stderr);sys.exit(1)
