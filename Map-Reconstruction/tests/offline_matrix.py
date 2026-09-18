#!/usr/bin/env python3
"""Run conversions and native routing across a directory of installed XODRs."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from carla_mapping.common import configuration,write_json
from carla_mapping.network import Network
from carla_mapping.lanelet import Writer
from carla_mapping.validation import validate

p=argparse.ArgumentParser();p.add_argument('source_dir',type=Path);p.add_argument('--report',type=Path,required=True);args=p.parse_args()
results=[]
for source in sorted(args.source_dir.glob('*.xodr')):
    start=time.monotonic()
    try:
        network=Network(source.read_text(),configuration())
        with tempfile.TemporaryDirectory(prefix='carla-offline-') as d:
            Writer(network).write(d)
            write_json(Path(d)/'network.json',network.summary());write_json(Path(d)/'config.json',network.config)
            report=validate(d)
            result=dict(map=source.stem,source_fingerprint=network.fingerprint,lanes=len(network.lanes),components=len(network.summary()['components']),
                        structural=report['structural']['status'],regulatory=report['regulatory']['status'],runtime='untested',
                        diagnostics=dict(Counter(x['code'] for x in network.diagnostics.items)),
                        structural_errors=report['structural'].get('errors',[])[:10],
                        native_routing={k:v for k,v in report['structural'].get('lanelet2',{}).items() if k not in ('edges','lane_changes')})
    except Exception as ex:
        result=dict(map=source.stem,status='failed',error=str(ex))
    result['seconds']=round(time.monotonic()-start,2);results.append(result)
    write_json(args.report,dict(carla_target='0.9.16',results=results))
    print(source.stem,result.get('structural',result.get('status')),result['seconds'],flush=True)
