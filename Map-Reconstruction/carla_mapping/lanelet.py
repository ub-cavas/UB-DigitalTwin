"""Deterministic Lanelet2 OSM export, with conservative control construction."""
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from .common import atomic_write, stable_id, write_json
from .network import speed_mps


class Writer:
    def __init__(self, network):
        self.net = network
        self.root = ET.Element('osm',version='0.6',generator='carla_mapping')
        ET.SubElement(self.root,'MetaInfo',format_version='1',map_version=network.fingerprint[:16])
        self.ids = {}
        self.nodes = {}
        self.ways = {}
        self.relations = {}
        self.parent = {}
        self.control_ids = {}
        self.lane_regs = {k:[] for k in network.lanes}

    def identifier(self, key):
        value = stable_id(key)
        if value in self.ids and self.ids[value] != key:
            raise ValueError(f'Deterministic ID collision: {key}, {self.ids[value]}')
        self.ids[value] = key
        return value

    def find(self,k):
        self.parent.setdefault(k,k)
        while self.parent[k]!=k:
            self.parent[k]=self.parent[self.parent[k]]; k=self.parent[k]
        return k

    def union(self,a,b):
        a,b = self.find(a),self.find(b)
        self.parent[max(a,b)] = min(a,b)

    @staticmethod
    def tags(element, values):
        for k,v in sorted(values.items()):
            ET.SubElement(element,'tag',k=k,v=str(v))

    def node(self,key,p,attrs=None):
        key = self.find(key)
        nid = self.identifier('node/'+key)
        if nid not in self.nodes:
            # Geographic placeholders: Local loader consumes local_x/y and ele.
            n = ET.SubElement(self.root,'node',id=str(nid),lat='0',lon='0',version='1')
            self.tags(n,dict(local_x=f'{p[0]:.9f}',local_y=f'{p[1]:.9f}',ele=f'{p[2]:.9f}',**(attrs or {})))
            self.nodes[nid] = np.asarray(p)
        return nid

    def way(self,key,points,attrs,node_keys=None,node_attrs=None):
        wid = self.identifier('way/'+key)
        if wid in self.ways: return wid
        ids = [self.node(node_keys[i] if node_keys else f'{key}/{i}',p,node_attrs[i] if node_attrs else None) for i,p in enumerate(points)]
        w = ET.SubElement(self.root,'way',id=str(wid),version='1')
        for nid in ids: ET.SubElement(w,'nd',ref=str(nid))
        self.tags(w,attrs)
        self.ways[wid] = ids
        return wid

    def relation(self,key,members,attrs):
        rid = self.identifier('relation/'+key)
        r = ET.SubElement(self.root,'relation',id=str(rid),version='1')
        for typ,ref,role in members: ET.SubElement(r,'member',type=typ,ref=str(ref),role=role)
        self.tags(r,attrs)
        self.relations[rid] = r
        return rid

    def endpoint(self,lane,side,end):
        key = lane.left_key if side=='left' else lane.right_key
        count = len(self.net.boundaries[key]['points'])
        index = count-1 if (end == 'exit') == lane.forward else 0
        return f'{key}/{index}'

    def join(self):
        for lane in sorted(self.net.lanes.values(),key=lambda l:l.key):
            for key in sorted(lane.successors):
                target = self.net.lanes[key]
                errors = [float(np.linalg.norm(getattr(lane,side)[-1]-getattr(target,side)[0])) for side in ('left','right')]
                if max(errors) <= self.net.config['join_tolerance']:
                    for side in ('left','right'):
                        self.union(self.endpoint(lane,side,'exit'),self.endpoint(target,side,'entry'))
                else:
                    self.net.diagnostics.add('connection_geometry',lane.key,f'Edge to {key} has boundary gaps {errors}; correct geometry/topology before routing')

    def boundary(self,key):
        boundary = self.net.boundaries[key]
        mark = boundary['marking']; kind = mark.get('type','unknown')
        subtypes = {'solid':'solid','broken':'dashed','solid solid':'solid_solid','solid broken':'solid_dashed','broken solid':'dashed_solid','broken broken':'dashed_dashed'}
        attrs = dict(type='line_thin',subtype=subtypes.get(kind,'solid'),lane_change='no')
        if kind=='curb': attrs.update(type='curbstone',subtype='high')
        elif kind in ('none','unknown'): attrs.update(type='virtual'); attrs.pop('subtype',None)
        elif kind not in subtypes:
            self.net.diagnostics.add('road_marking',key,f'Unsupported marking {kind}; lane changing disabled','regulatory')
        change=mark.get('laneChange')
        if change=='both': attrs['lane_change']='yes'
        elif change in ('increase','decrease'):
            attrs.update({'lane_change:left':'yes' if change=='increase' else 'no','lane_change:right':'yes' if change=='decrease' else 'no'})
            attrs.pop('lane_change')
        elif change is None:
            # OpenDRIVE defaults laneChange to both, but crossing solid lines is prohibited.
            if kind in ('broken','broken broken'): attrs['lane_change']='yes'
            elif kind in ('none','unknown'):
                self.net.diagnostics.add('unknown_lane_change',key,'No marking or lane-change evidence; crossing disabled pending review','regulatory')
        if mark.get('color') in ('white','yellow'): attrs['color']=mark['color']
        return self.way(key,boundary['points'],attrs)

    def controls(self):
        for key,c in sorted(self.net.controls.items()):
            mapping=dict(kind=c['kind'],source_id=c['id'],lanelets=[self.identifier('relation/'+k) for k in c['lanes']],regulatory_elements=[])
            self.control_ids[key]=mapping
            bounds = self.net.config['bounds']
            position = c.get('position')
            if bounds and not c['lanes'] and position and not (bounds[0] <= position[0] <= bounds[2] and bounds[1] <= position[1] <= bounds[3]):
                mapping['status']='outside_selected_region'; continue
            if c.get('exclude'):
                mapping['status']='excluded_by_correction'; continue
            issues=[]; kind=c['kind']; members=[]
            if not c['lanes']: issues.append('affected lane associations')
            if kind in ('traffic_light','stop','yield') and not c.get('stop_line'): issues.append('stop line')
            if kind in ('traffic_light','stop','yield') and not c.get('geometry'): issues.append('control geometry')
            if kind=='traffic_light' and not c.get('bulbs'): issues.append('bulb positions/colors')
            if kind=='yield' and not c.get('right_of_way_lanes'): issues.append('priority lanes')
            if kind=='crosswalk' and (not c.get('geometry') or len(c['geometry'])!=4): issues.append('four-corner crosswalk geometry and pedestrian direction')
            if kind=='unresolved': issues.append('control classification')
            if kind=='speed_limit':
                value=c.get('speed',{})
                attrs=c.get('attributes',{})
                try:
                    speed=speed_mps(value.get('value',attrs.get('value')),value.get('unit',attrs.get('unit','')))
                    if speed is None: issues.append('speed value')
                except (ValueError,TypeError): issues.append('speed value/unit'); speed=None
            if issues:
                mapping.update(status='unresolved',missing=issues)
                self.net.diagnostics.add('unresolved_control',key,'Supply corrections/runtime evidence for: '+', '.join(issues),'regulatory')
                continue
            if kind=='crosswalk':
                p=c['geometry']
                left=self.way(key+'/left',[p[0],p[1]],dict(type='virtual',lane_change='no'))
                right=self.way(key+'/right',[p[3],p[2]],dict(type='virtual',lane_change='no'))
                cross=self.relation(key+'/crosswalk',[('way',left,'left'),('way',right,'right')],dict(type='lanelet',subtype='crosswalk',location='urban',**{'participant:pedestrian':'yes','participant:vehicle':'no'}))
                members=[('relation',cross,'refers')]; subtype='crosswalk'
            elif kind=='yield':
                members=[('relation',self.identifier('relation/'+k),'right_of_way') for k in c['right_of_way_lanes']]
                members += [('relation',self.identifier('relation/'+k),'yield') for k in c.get('yield_lanes',c['lanes'])]
                subtype='right_of_way'
            elif kind=='speed_limit':
                for lane in c['lanes']: self.net.lanes[lane].speed=speed
                subtype='speed_limit'
            else:
                a=c.get('attributes',{})
                shapeattrs=dict(type='traffic_light' if kind=='traffic_light' else 'traffic_sign',subtype='red_yellow_green' if kind=='traffic_light' else 'stop_sign')
                if kind=='traffic_light':
                    height=c.get('height',a.get('height'))
                    if height is None or float(height)<=0:
                        self.net.diagnostics.add('light_height',key,'Supply positive traffic-light height','regulatory'); mapping['status']='unresolved'; continue
                    shapeattrs['height']=height
                geometry=self.way(key+'/geometry',c['geometry'],shapeattrs)
                members=[('way',geometry,'refers')]
                subtype='traffic_light' if kind=='traffic_light' else 'traffic_sign'
                if kind=='traffic_light':
                    bulbs=c['bulbs']
                    bw=self.way(key+'/bulbs',[b['position'] for b in bulbs],dict(type='light_bulbs',traffic_light_id=geometry),node_attrs=[{k:b[k] for k in ('color','arrow') if k in b} for b in bulbs])
                    members.append(('way',bw,'light_bulbs')); mapping['traffic_light_way']=geometry
            if c.get('stop_line'):
                stop=self.way(key+'/stop_line',c['stop_line'],dict(type='stop_line'))
                members.append(('way',stop,'ref_line')); mapping['stop_line']=stop
            attrs=dict(type='regulatory_element',subtype=subtype)
            if kind=='speed_limit': attrs['sign_type']=f'{speed*3.6:.9g} km/h'
            rid=self.relation(key,members,attrs)
            for lane in c['lanes']: self.lane_regs[lane].append(rid)
            mapping.update(status='generated',regulatory_elements=[rid])

    def write(self, directory):
        directory=Path(directory)
        self.join()
        self.controls()
        lane_ids={}
        for key,lane in sorted(self.net.lanes.items()):
            left,right=self.boundary(lane.left_key),self.boundary(lane.right_key)
            attrs=dict(type='lanelet',subtype='road',location='urban',one_way='yes',source_id=key,**{'participant:vehicle':'yes'})
            if lane.speed is not None: attrs['speed_limit']=f'{lane.speed*3.6:.9g} km/h'
            else: self.net.diagnostics.add('missing_speed',key,'No source speed limit; supply a speed_limits correction','regulatory')
            if lane.turn:
                attrs['turn_direction']=lane.turn
                if not self.lane_regs[key]:
                    self.net.diagnostics.add('junction_rules',key,'Junction movement has no resolved control/priority association','regulatory')
            members=[('way',left,'left'),('way',right,'right')]+[('relation',rid,'regulatory_element') for rid in self.lane_regs[key]]
            lane_ids[key]=self.relation(key,members,attrs)
        # XML primitives must be grouped (controls may create relations before lane boundaries).
        self.root[:]=sorted(self.root,key=lambda e:({'MetaInfo':0,'node':1,'way':2,'relation':3}[e.tag],int(e.get('id',0))))
        ET.indent(self.root)
        atomic_write(directory/'lanelet2_map.osm',ET.tostring(self.root,encoding='utf-8',xml_declaration=True))
        atomic_write(directory/'map_projector_info.yaml','projector_type: Local\n')
        mapping=dict(source_fingerprint=self.net.fingerprint,lanes=lane_ids,controls=self.control_ids,
                     boundaries={k:self.identifier('way/'+k) for k in sorted({b for l in self.net.lanes.values() for b in (l.left_key,l.right_key)})})
        write_json(directory/'id_mapping.json',mapping)
        return mapping
