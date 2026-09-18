import importlib.util
import json
import math
from pathlib import Path
import queue
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import yaml
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from carla_mapping.common import configuration, fingerprint, write_json
from carla_mapping.network import Network, speed_mps
from carla_mapping.lanelet import Writer
from carla_mapping.cloud import VoxelStore, read_pcd, measurement_points, SEMANTIC
from carla_mapping.capture import Inbox
from carla_mapping.validation import native_routing
from fixtures import document, road, lane, connected


class Geometry(unittest.TestCase):
    def network(self,source): return Network(source,configuration())

    def test_connected_ids_and_native_routing(self):
        n=self.network(connected())
        with tempfile.TemporaryDirectory() as d:
            w=Writer(n); first=w.write(d)
            content=(Path(d)/'lanelet2_map.osm').read_bytes()
            Writer(self.network(connected())).write(d)
            self.assertEqual(content,(Path(d)/'lanelet2_map.osm').read_bytes())
            native=native_routing(Path(d)/'lanelet2_map.osm')
            self.assertEqual(native['status'],'passed')
            keys=list(n.lanes)
            self.assertEqual(native['edges'],[[first['lanes'][keys[0]],first['lanes'][keys[1]]]])

    def test_shared_boundaries_lane_changes(self):
        n=self.network(document(road(lanes=lane(-1)+lane(-2))))
        a,b=list(n.lanes.values())
        self.assertEqual(a.right_key,b.left_key)
        with tempfile.TemporaryDirectory() as d:
            mapping=Writer(n).write(d)
            native=native_routing(Path(d)/'lanelet2_map.osm')
            self.assertEqual(native['status'],'passed')
            self.assertEqual(len(native['lane_changes']),2)

    def test_curves_spirals_polynomials(self):
        shapes=['<arc curvature="0.05"/>','<spiral curvStart="0" curvEnd="0.1"/>','<paramPoly3 aU="0" bU="12" cU="0" dU="0" aV="0" bV="0" cV="2" dV="0" pRange="normalized"/>','<poly3 a="0" b="0" c="0.01" d="0"/>']
        for shape in shapes:
            with self.subTest(shape=shape):
                n=self.network(document(road(shape=shape)))
                self.assertEqual(len(n.lanes),1)
                for l in n.lanes.values():
                    self.assertLessEqual(np.linalg.norm(np.diff(l.left,axis=0),axis=1).max(),1.)
                    self.assertGreater(abs(l.left[-1,1]),.1)

    def test_taper_marking_speed_splits(self):
        extra='<width sOffset="6" a="3.5" b="0.1" c="0" d="0"/><roadMark sOffset="4" type="solid" laneChange="none"/><speed sOffset="8" max="20" unit="mph"/>'
        n=self.network(document(road(lanes=lane(extra=extra))))
        self.assertEqual(len(n.lanes),3)
        values=list(n.lanes.values())
        self.assertAlmostEqual(values[-1].speed,8.9408)
        self.assertAlmostEqual(np.linalg.norm(values[-1].left[-1]-values[-1].right[-1]),4.1)
        self.assertEqual(sum(len(l.successors) for l in values),2)

    def test_left_hand_direction_and_slope_banking(self):
        source=document(road(lanes=lane(1),rule='LHT',bank='<superelevation s="0" a="0.1" b="0" c="0" d="0"/>',elevation='')).replace('a="0" b="0" c="0" d="0"/></elevationProfile>','a="0" b="0.1" c="0" d="0"/></elevationProfile>')
        n=self.network(source); l=next(iter(n.lanes.values()))
        self.assertTrue(l.forward)
        self.assertGreater(l.left[0,2],l.right[0,2])
        self.assertGreater(l.center[-1,2],l.center[0,2])
        self.assertGreater(n.stations()[0]['pitch'],0)
        self.assertGreater(n.stations()[0]['roll'],0)

    def test_stacked_and_disconnected(self):
        n=self.network(document(road('1'),road('2',z=8),road('3',x=100)))
        self.assertEqual(len(n.summary()['components']),3)
        self.assertEqual(sum(len(l.successors) for l in n.lanes.values()),0)
        self.assertEqual({round(s['xyz'][2]) for s in n.stations()},{0,8})

    def test_invalid_source_is_diagnostic(self):
        with self.assertRaises(ValueError): self.network('<invalid/>')
        n=self.network(document(road(shape='<unknown/>')))
        self.assertEqual(len(n.lanes),0)
        self.assertTrue(n.diagnostics.errors())
        n=self.network(document(road().replace('length="12"','length="nan"',1)))
        self.assertTrue(n.diagnostics.errors())

    def test_speed_units(self):
        self.assertEqual(speed_mps(36,'km/h'),10.)
        self.assertAlmostEqual(speed_mps(10,'mph'),4.4704)
        self.assertEqual(speed_mps(10,'m/s'),10.)
        with self.assertRaises(ValueError): speed_mps(10,'knots')

    def test_corrections_reject_stale_and_fix_speed(self):
        n=self.network(connected()); keys=list(n.lanes)
        data=dict(version=1,source_fingerprint=n.fingerprint,speed_limits={keys[0]:dict(value=15,unit='mph')},connections=[{'from':keys[0],'to':keys[1],'action':'remove'}])
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'fix.yaml';p.write_text(yaml.safe_dump(data));n.corrections(p)
            self.assertAlmostEqual(n.lanes[keys[0]].speed,6.7056)
            self.assertFalse(n.lanes[keys[0]].successors)
            data['source_fingerprint']='stale';p.write_text(yaml.safe_dump(data))
            with self.assertRaises(ValueError): n.corrections(p)

    def test_controls_no_fabricated_bulbs(self):
        source=document(road(extra='<signals><signal id="5" s="6" t="2" dynamic="yes" type="1000001" orientation="+" height="1"><validity fromLane="-1" toLane="-1"/></signal></signals>'))
        n=self.network(source)
        with tempfile.TemporaryDirectory() as d:
            result=Writer(n).write(d)
            self.assertEqual(result['controls']['signal/1/5']['status'],'unresolved')
            self.assertIn('bulb positions/colors',result['controls']['signal/1/5']['missing'])
            c=n.controls['signal/1/5'];c.update(geometry=[[5,2,3],[5,3,3]],stop_line=[[5,0,0],[5,-3.5,0]],bulbs=[dict(position=[5,2,3],color='red'),dict(position=[5,2,3.5],color='green')])
            result=Writer(n).write(d)
            self.assertEqual(result['controls']['signal/1/5']['status'],'generated')

    def test_junction_merge_and_roundabout_topology(self):
        # Two incoming roads explicitly enter one connecting road; spatial overlap alone contributes no edges.
        a=road('1',lanes=lane(post=-1),link='<successor elementType="junction" elementId="9"/>')
        b=road('2',y=-4,lanes=lane(post=-1),link='<successor elementType="junction" elementId="9"/>')
        c=road('3',x=12,junction='9',lanes=lane(post=-1),link='<successor elementType="road" elementId="3" contactPoint="start"/>',shape='<arc curvature="0.05"/>')
        j='<junction id="9">'+''.join(f'<connection id="{i}" incomingRoad="{i}" connectingRoad="3" contactPoint="start"><laneLink from="-1" to="-1"/></connection>' for i in (1,2))+'</junction>'
        n=self.network(document(a,b,c,extra=j))
        self.assertEqual(sum(len(l.successors) for l in n.lanes.values()),3)
        self.assertEqual(len(n.summary()['components']),1)


class Cloud(unittest.TestCase):
    def test_resume_tiles_and_single_equivalence(self):
        config=configuration(); identity={'source':'fixture','config':config}
        points=np.array([[-.01,0,0,.5],[0,0,0,.6],[19.99,0,0,.7],[20,0,0,.8],[0,0,8,.9]],dtype='<f4')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);store=VoxelStore(root/'capture',identity,config)
            store.commit_station('one',[points],{});store.close()
            store=VoxelStore(root/'capture',identity,config,True)
            self.assertFalse(store.commit_station('one',[points],{}))
            self.assertEqual(store.count(),5)
            store.export(root,'tiled')
            tiled=np.concatenate([read_pcd(p) for p in sorted((root/'pointcloud_map.pcd').glob('*.pcd'))])
            (root/'single').mkdir();store.export(root/'single','single')
            single=read_pcd(root/'single/pointcloud_map.pcd')
            self.assertEqual(set(map(tuple,single)),set(map(tuple,tiled)))
            meta=yaml.safe_load((root/'pointcloud_map_metadata.yaml').read_text())
            self.assertEqual(meta['tile_-1_0.pcd'],[-20.,0.])
            store.close()
            with self.assertRaises(ValueError): VoxelStore(root/'capture',{'changed':True},config,True)

    def test_transaction_rollback_disk_exhaustion_and_limits(self):
        config=configuration()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);store=VoxelStore(root/'capture',{},config)
            points=np.array([[1,2,3,.5]],dtype='<f4')
            store.commit_station('complete',[points],{})
            def interrupted():
                yield points+1
                raise OSError(28,'No space left on device')
            with self.assertRaises(OSError): store.commit_station('partial',interrupted(),{})
            self.assertEqual(store.completed(),{'complete'});self.assertEqual(store.count(),1)
            with self.assertRaises(ValueError): store.commit_station('far',[np.array([[1e9,0,0,1]],dtype='<f4')],{})
            self.assertEqual(store.count(),1);store.close()

    def test_late_scans_bounded_queue_future_and_timeout(self):
        from types import SimpleNamespace
        inbox=Inbox(2);inbox.put(SimpleNamespace(frame=1));inbox.put(SimpleNamespace(frame=2));inbox.put(SimpleNamespace(frame=3))
        self.assertEqual(inbox.dropped,1)
        self.assertEqual(inbox.frame(2,.1).frame,2);self.assertEqual(inbox.late,1)
        with self.assertRaises(TimeoutError): inbox.frame(3,.001)
        inbox.put(SimpleNamespace(frame=5))
        with self.assertRaises(RuntimeError): inbox.frame(4,.1)

    def test_dynamic_filter_measurement_alignment(self):
        import carla
        from types import SimpleNamespace
        raw=np.zeros(2,dtype=SEMANTIC);raw['x']=1;raw['label']=[1,14]
        measure=SimpleNamespace(raw_data=raw.tobytes(),transform=carla.Transform(carla.Location(10,20,3),carla.Rotation(yaw=90)))
        points,labels,removed=measurement_points(measure)
        self.assertEqual(removed,1);np.testing.assert_allclose(points[0,:3],[10,-21,3],atol=1e-6)
        self.assertAlmostEqual(points[0,3],math.exp(-.004),places=6)


if __name__=='__main__': unittest.main()

class Robustness(unittest.TestCase):
    def test_real_sqlite_disk_limit_rolls_back(self):
        with tempfile.TemporaryDirectory() as d:
            config=configuration();store=VoxelStore(Path(d)/'capture',{},config)
            store.commit_station('safe',[np.array([[1,2,3,.5]],dtype='<f4')],{})
            pages=store.db.execute('PRAGMA page_count').fetchone()[0]
            store.db.execute(f'PRAGMA max_page_count={pages}')
            points=np.column_stack([np.arange(10000)*.2,np.zeros(10000),np.zeros(10000),np.ones(10000)]).astype('<f4')
            with self.assertRaises(sqlite3.OperationalError): store.commit_station('full',[points],{})
            self.assertEqual(store.completed(),{'safe'});self.assertEqual(store.count(),1)
            store.close()

    def test_section_offset_jump_compensated_by_lane_width(self):
        source=document(road(length=12,lanes=lane(-1,pre=-1,post=-1)))
        first='<laneSection s="0"><right>'+lane(-1,post=-1)+'</right></laneSection>'
        second='<laneSection s="6"><right>'+lane(-1,pre=-1)+'</right></laneSection>'
        # A change in section itself must not introduce a discontinuity.
        import xml.etree.ElementTree as ET
        root=ET.fromstring(source); lanes=root.find('road/lanes')
        for e in list(lanes): lanes.remove(e)
        lanes.extend([ET.fromstring(first),ET.fromstring(second)])
        n=Network(ET.tostring(root,encoding='unicode'),configuration())
        self.assertEqual(len(n.lanes),2)
        self.assertFalse(n.diagnostics.errors())
        a,b=list(n.lanes.values());np.testing.assert_allclose(a.center[-1],b.center[0],atol=1e-8)

    def test_unsupported_profile_not_ready_and_bounds_3d(self):
        n=Network(document(road(bank='<shape s="0" t="0" a="1" b="0" c="0" d="0"/>')),configuration())
        self.assertTrue(n.diagnostics.errors())
        config=configuration(overrides={'bounds':[0,-4,10,1]})
        n=Network(document(road('1'),road('2',z=10),road('3',x=100)),config)
        self.assertEqual(len(n.lanes),2)
        self.assertEqual({round(s['xyz'][2]) for s in n.stations()},{0,10})

    def test_validation_marks_missing_runtime_untested(self):
        from carla_mapping.validation import validate
        n=Network(connected(),configuration())
        with tempfile.TemporaryDirectory() as d:
            Writer(n).write(d);write_json(Path(d)/'network.json',n.summary());write_json(Path(d)/'config.json',n.config)
            report=validate(d)
            self.assertFalse(report['ready']);self.assertEqual(report['coverage']['status'],'untested')
            self.assertTrue(all(x['status']=='untested' for x in report['runtime'].values()))

    def test_export_failure_keeps_completed_pcd(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);store=VoxelStore(root/'capture',{},configuration())
            store.commit_station('safe',[np.array([[1,2,3,.5]],dtype='<f4')],{})
            store.export(root,'single');before=(root/'pointcloud_map.pcd').read_bytes()
            with patch('carla_mapping.cloud.os.replace',side_effect=OSError(28,'disk full')):
                with self.assertRaises(OSError):store.export(root,'single')
            self.assertEqual(before,(root/'pointcloud_map.pcd').read_bytes());self.assertEqual(store.completed(),{'safe'});store.close()

class VoxelCache(unittest.TestCase):
    def test_overlap_eviction_and_rollback_preserve_first_return(self):
        with tempfile.TemporaryDirectory() as d:
            store=VoxelStore(Path(d)/'capture',{},configuration())
            store._known_limit=2
            first=np.array([[.01,0,0,.2],[.09,0,0,.9],[.11,0,0,.3]],dtype='<f4')
            store.commit_station('first',[first],{})
            def fail():
                yield np.array([[.31,0,0,.4]],dtype='<f4')
                raise OSError('interrupted')
            with self.assertRaises(OSError):store.commit_station('bad',fail(),{})
            store.commit_station('next',[np.array([[.31,0,0,.5],[.41,0,0,.6],[.09,0,0,.8]],dtype='<f4')],{})
            self.assertLessEqual(len(store._known),2)
            rows=store.db.execute('SELECT x,intensity FROM voxels ORDER BY ix').fetchall()
            np.testing.assert_allclose(rows,[[.01,.2],[.11,.3],[.31,.5],[.41,.6]])
            self.assertEqual(store.completed(),{'first','next'})
            store.close()
