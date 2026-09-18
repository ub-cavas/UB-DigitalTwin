"""Coordinate, filtering, voxel, and binary-format checks for the PCD mapper."""
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import carla
import numpy as np

SPEC=importlib.util.spec_from_file_location('remap_carla',Path(__file__).parents[1]/'pointcloud/remap_carla.py')
mapper=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(mapper)


class RemappingTests(unittest.TestCase):
    def test_scan_pose_transform_and_dynamic_filter(self):
        records=np.array([(1,2,3,.2,1,1),(5,5,5,.9,2,14)],dtype=mapper.SEMANTIC)
        measurement=SimpleNamespace(raw_data=records.tobytes(),transform=carla.Transform(carla.Location(10,20,3),carla.Rotation(yaw=90)))
        pts,labels,removed=mapper.measurement_points(measurement,[14])
        np.testing.assert_allclose(pts[0,:3],[8,-21,6],atol=1e-5)
        self.assertEqual(removed,1);self.assertEqual(labels[1],1);self.assertEqual(labels[14],1)
        self.assertAlmostEqual(float(pts[0,3]),float(np.exp(-.004*np.sqrt(14))),places=6)

    def test_negative_voxels_do_not_alias_positive_voxels(self):
        points=np.array([[-.01,0,0,1],[.01,0,0,1],[.09,0,0,.5],[.11,0,0,1]],dtype=np.float32)
        result=mapper.reduce_cloud(points,.1)
        self.assertEqual(len(result),3)
        self.assertTrue(any(np.all(row==points[0]) for row in result))
        self.assertTrue(any(np.all(row==points[1]) for row in result))

    def test_binary_pcd_payload_is_xyzi_float32(self):
        points=np.array([[1,2,3,.5],[-1,-2,-3,1]],dtype=np.float32)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'cloud.pcd';mapper.write_pcd(path,points)
            header,payload=path.read_bytes().split(b'DATA binary\n',1)
            self.assertIn(b'FIELDS x y z intensity',header)
            self.assertIn(b'POINTS 2\n',header)
            np.testing.assert_array_equal(np.frombuffer(payload,dtype='<f4').reshape(-1,4),points)

    def test_survey_aligns_reversed_boundary(self):
        xml='''<osm>
        <node id="1"><tag k="local_x" v="0"/><tag k="local_y" v="0"/></node>
        <node id="2"><tag k="local_x" v="10"/><tag k="local_y" v="0"/></node>
        <node id="3"><tag k="local_x" v="10"/><tag k="local_y" v="-4"/></node>
        <node id="4"><tag k="local_x" v="0"/><tag k="local_y" v="-4"/></node>
        <way id="5"><nd ref="1"/><nd ref="2"/></way>
        <way id="6"><nd ref="3"/><nd ref="4"/></way>
        <relation id="7"><member role="left" ref="5"/><member role="right" ref="6"/>
        <tag k="type" v="lanelet"/></relation></osm>'''
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'map.osm';path.write_text(xml)
            poses=mapper.survey_poses(path,3)
        np.testing.assert_allclose(poses[:,1],-2)
        np.testing.assert_allclose(poses[[0,-1],0],[0,10])
        self.assertLessEqual(np.diff(poses[:,0]).max(),3)


if __name__=='__main__':unittest.main()
