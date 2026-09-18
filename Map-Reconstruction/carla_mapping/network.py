"""OpenDRIVE road surfaces and source-linked, directed driving lanes.

Coordinates here are OpenDRIVE/Autoware Local, not Unreal coordinates. Unsupported
constructs remain explicit diagnostics; no proximity-derived road connections.
"""
from dataclasses import dataclass, field
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
from scipy.integrate import quad
import yaml

from .common import Diagnostics, fingerprint


def number(e, name, default=0.0):
    value = float(e.get(name, default))
    if not math.isfinite(value):
        raise ValueError(f'Nonfinite {name} in {e.tag}')
    return value


def active(elements, s, key='s'):
    result = None
    for e in elements:
        if number(e, key) <= s:
            result = e
        else:
            break
    return result


def polynomial(elements, s, key='s', derivative=False):
    e = active(elements, s, key)
    if e is None:
        return 0.0
    ds = max(0., s - number(e, key))
    a, b, c, d = (number(e, k) for k in 'abcd')
    return b + 2*c*ds + 3*d*ds*ds if derivative else a + ds*(b + ds*(c + ds*d))


def speed_mps(value, unit):
    if str(value).lower() in ('no limit', 'undefined', '-1'):
        return None
    factors = {'m/s': 1., 'km/h': 1/3.6, 'mph': 0.44704}
    if unit not in factors:
        raise ValueError(f'Unsupported speed unit {unit!r}')
    value = float(value) * factors[unit]
    if not math.isfinite(value) or value <= 0:
        raise ValueError('Speed must be finite and positive')
    return value


class Road:
    def __init__(self, element, diagnostics):
        self.e = element
        self.id = element.get('id')
        self.length = number(element, 'length')
        if self.length <= 0:
            raise ValueError(f'Road {self.id} has no positive length')
        self.rule = element.get('rule', 'RHT')
        self.geometries = element.findall('planView/geometry')
        self.sections = element.findall('lanes/laneSection')
        if not self.geometries or not self.sections:
            raise ValueError(f'Road {self.id} has no planView or laneSection')
        self.elevations = element.findall('elevationProfile/elevation')
        self.banks = element.findall('lateralProfile/superelevation')
        self.offsets = element.findall('lanes/laneOffset')
        self.diag = diagnostics
        if self.rule not in ('RHT', 'LHT'):
            diagnostics.add('driving_side', self.id, f'Unsupported road rule {self.rule}')
        for path in ('lateralProfile/crossfall', 'lateralProfile/shape', 'surface/CRG'):
            entries = element.findall(path)
            if any(e.tag == 'CRG' or any(abs(number(e, k)) > 1e-9 for k in 'abcd') for e in entries):
                diagnostics.add('unsupported_surface', self.id, f'{path} requires a surface evaluator; output is review-only')
        for section in self.sections:
            if section.get('singleSide') == 'true':
                diagnostics.add('single_side_section', self.id, 'singleSide lane sections require reconciliation')
            for lane in section.findall('./*/lane'):
                if lane.find('border') is not None or any(abs(number(h,k)) > 1e-9 for h in lane.findall('height') for k in ('inner','outer')) or (lane.get('level') == 'true' and any(abs(number(b,k)) > 1e-9 for b in self.banks for k in 'abcd')):
                    diagnostics.add('unsupported_lane_surface', f'{self.id}/{lane.get("id")}', 'Lane border/height/level constructs require review', severity='error' if lane.get('type') == 'driving' else 'warning')
                if lane.get('direction') not in (None, 'standard'):
                    diagnostics.add('lane_direction', f'{self.id}/{lane.get("id")}', 'Explicit lane direction override is unsupported')
        for entries, key in [(self.geometries, 's'), (self.sections, 's'), (self.elevations, 's'), (self.banks, 's'), (self.offsets, 's')]:
            positions = [number(e, key) for e in entries]
            if positions != sorted(set(positions)):
                raise ValueError(f'Road {self.id} has unordered or duplicate {key} records')
        if abs(number(self.geometries[0], 's')) > 1e-6 or abs(number(self.sections[0], 's')) > 1e-6:
            raise ValueError(f'Road {self.id} does not start at s=0')
        for i, g in enumerate(self.geometries):
            end = number(self.geometries[i+1], 's') if i+1 < len(self.geometries) else self.length
            if abs(number(g, 's') + number(g, 'length') - end) > .01:
                diagnostics.add('geometry_gap', self.id, f'Noncontiguous planView at {g.get("s")}')

    def forward(self, lane_id):
        return (lane_id < 0) == (self.rule == 'RHT')

    def reference(self, s):
        g = active(self.geometries, s)
        ds = max(0., min(s - number(g, 's'), number(g, 'length')))
        x, y, h = (number(g, k) for k in ('x', 'y', 'hdg'))
        shape = next(iter(g))
        if shape.tag == 'line':
            u, v, angle = ds, 0., 0.
        elif shape.tag == 'arc':
            k = number(shape, 'curvature')
            u, v, angle = (math.sin(k*ds)/k, (1-math.cos(k*ds))/k, k*ds) if abs(k) > 1e-12 else (ds, 0., 0.)
        elif shape.tag == 'spiral':
            k0, k1 = number(shape, 'curvStart'), number(shape, 'curvEnd')
            rate = (k1-k0) / number(g, 'length')
            angle = k0*ds + .5*rate*ds*ds
            u = quad(lambda t: math.cos(k0*t + .5*rate*t*t), 0, ds, epsabs=1e-8)[0]
            v = quad(lambda t: math.sin(k0*t + .5*rate*t*t), 0, ds, epsabs=1e-8)[0]
        elif shape.tag == 'paramPoly3':
            p = ds / number(g, 'length') if shape.get('pRange') == 'normalized' else ds
            def poly(axis):
                a,b,c,d = [number(shape, k+axis) for k in 'abcd']
                return a+p*(b+p*(c+p*d)), b+p*(2*c+3*p*d)
            u, du = poly('U'); v, dv = poly('V')
            angle = math.atan2(dv, du)
        elif shape.tag == 'poly3':
            a,b,c,d = [number(shape, k) for k in 'abcd']
            # poly3 uses arc length s, not its local u parameter.
            from scipy.optimize import brentq
            length = lambda u: quad(lambda t: math.hypot(1, b+2*c*t+3*d*t*t), 0, u)[0]
            u = brentq(lambda u: length(u)-ds, 0, ds) if ds > 0 else 0.
            v = a+u*(b+u*(c+u*d)); angle = math.atan(b+2*c*u+3*d*u*u)
        else:
            raise ValueError(f'Unsupported geometry {shape.tag} on road {self.id}')
        return np.array([x+math.cos(h)*u-math.sin(h)*v, y+math.sin(h)*u+math.cos(h)*v,
                         polynomial(self.elevations, s)]), h+angle

    def surface(self, s, t):
        p, heading = self.reference(s)
        pitch = math.atan(polynomial(self.elevations, s, derivative=True))
        bank = polynomial(self.banks, s)
        # Rz(heading) Ry(-pitch) Rx(bank) applied to the lateral unit vector.
        lateral = np.array([-math.sin(heading)*math.cos(bank)-math.cos(heading)*math.sin(pitch)*math.sin(bank),
                            math.cos(heading)*math.cos(bank)-math.sin(heading)*math.sin(pitch)*math.sin(bank),
                            math.cos(pitch)*math.sin(bank)])
        return p + t*lateral

    def lane_elements(self, section):
        return {int(x.get('id')): x for x in self.sections[section].findall('./*/lane')}

    def boundary_t(self, section, boundary, s):
        result = polynomial(self.offsets, s)
        lanes = self.lane_elements(section)
        if boundary:
            sign = 1 if boundary > 0 else -1
            for lid in range(sign, boundary+sign, sign):
                if lid not in lanes:
                    raise ValueError(f'Noncontiguous lane IDs on road {self.id}')
                widths = lanes[lid].findall('width')
                if not widths:
                    raise ValueError(f'No width for road {self.id}, lane {lid}')
                w = polynomial(widths, s-number(self.sections[section], 's'), 'sOffset')
                if w < -1e-5:
                    raise ValueError(f'Negative lane width on road {self.id}, lane {lid}')
                result += sign * max(0., w)
        return result

    def boundary(self, section, boundary, s):
        # Lane sections can change laneOffset and compensate it with new lane
        # widths at the same s. The old section must use its left-hand limit.
        if section+1 < len(self.sections):
            end = number(self.sections[section+1], 's')
            if s >= end:
                s = math.nextafter(end, -math.inf)
        return self.surface(s, self.boundary_t(section, boundary, s))


@dataclass
class Lane:
    key: str
    road: str
    section: int
    lane_id: int
    start: float
    end: float
    forward: bool
    left_key: str
    right_key: str
    left: np.ndarray
    right: np.ndarray
    samples: np.ndarray
    speed: float = None
    turn: str = None
    successors: set = field(default_factory=set)

    @property
    def center(self):
        return (self.left+self.right)/2


class Network:
    def __init__(self, source, config):
        self.source = source
        self.fingerprint = fingerprint(source)
        self.config = config
        self.diagnostics = Diagnostics()
        root = ET.fromstring(source)
        if root.tag != 'OpenDRIVE':
            raise ValueError('Expected an OpenDRIVE document')
        self.root = root
        self.roads = {}
        self.lanes = {}
        self.boundaries = {}
        self.controls = {}
        self.correction_hash = None
        for e in root.findall('road'):
            key = e.get('id')
            if key in self.roads:
                raise ValueError(f'Duplicate road ID {key}')
            try:
                self.roads[key] = Road(e, self.diagnostics)
            except (ValueError, TypeError) as ex:
                self.diagnostics.add('invalid_road', key, str(ex))
        self._sample()
        self._connect()
        self._controls()
        if not self.lanes:
            self.diagnostics.add('empty_network', 'map', 'No usable driving lanes in selected region')

    def _sample(self):
        for road in self.roads.values():
            for si, section in enumerate(road.sections):
                try:
                    self._section(road, si, section)
                except (ValueError, KeyError, TypeError) as ex:
                    self.diagnostics.add('invalid_section', f'road/{road.id}/section/{si}', str(ex))

    def _section(self, road, si, section):
        a = number(section, 's')
        b = number(road.sections[si+1], 's') if si+1 < len(road.sections) else road.length
        lanes = road.lane_elements(si)
        driving = {i:e for i,e in lanes.items() if i and e.get('type') == 'driving'}
        if not driving:
            return
        splits = {a,b}
        for lane in lanes.values():
            for tag in ('roadMark', 'speed', 'access', 'rule', 'material'):
                splits.update(a+number(e, 'sOffset') for e in lane.findall(tag) if a < a+number(e, 'sOffset') < b)
            if lane.find('access') is not None or lane.find('rule') is not None:
                self.diagnostics.add('lane_rules', f'road/{road.id}/section/{si}/lane/{lane.get("id")}', 'Access/rule records require explicit review', 'regulatory')
        splits.update(number(e,'s') for e in road.e.findall('type') + road.e.findall('signals/signal') + road.e.findall('signals/signalReference') if a < number(e,'s') < b)
        splits = sorted(splits)
        indices = {i for lid in driving for i in (lid, lid-(1 if lid>0 else -1))}
        for start, end in zip(splits, splits[1:]):
            if end-start < 1e-6:
                continue
            knots = {start,end}
            for entries,key,offset in [(road.geometries,'s',0), (road.elevations,'s',0), (road.banks,'s',0), (road.offsets,'s',0)]:
                knots.update(number(e,key)+offset for e in entries if start < number(e,key)+offset < end)
            for lane in lanes.values():
                knots.update(a+number(e,'sOffset') for e in lane.findall('width') if start < a+number(e,'sOffset') < end)
            cache = {}
            def points(s):
                if s not in cache:
                    cache[s] = np.array([road.boundary(si, i, s) for i in sorted(indices)])
                return cache[s]
            def refine(lo, hi, depth=0):
                p,q = points(lo),points(hi)
                mid = (lo+hi)/2
                err = np.linalg.norm(points(mid)-(p+q)/2, axis=1).max()
                # Quarter samples detect inflection curves with coincident midpoints.
                err = max(err, np.linalg.norm(points((3*lo+hi)/4)-(3*p+q)/4,axis=1).max(),
                          np.linalg.norm(points((lo+3*hi)/4)-(p+3*q)/4,axis=1).max())
                if np.linalg.norm(q-p,axis=1).max() > self.config['max_spacing'] or hi-lo > self.config['max_spacing'] or err > self.config['chord_error']:
                    if depth >= 20:
                        raise ValueError('Adaptive sampling failed to converge; discontinuous geometry')
                    return refine(lo,mid,depth+1)[:-1]+refine(mid,hi,depth+1)
                return [lo,hi]
            knots = sorted(knots)
            ss = []
            for lo,hi in zip(knots,knots[1:]):
                ss += refine(lo,hi)[:-1]
            ss.append(end)
            ss = np.asarray(ss)
            boundary_keys = {}
            for index in sorted(indices):
                key = f'road/{road.id}/section/{si}/boundary/{index}/segment/{start:.9f}'
                pts = np.array([road.boundary(si,index,s) for s in ss])
                owner = lanes.get(index)
                mark = active(owner.findall('roadMark'), (start+end)/2-a, 'sOffset') if owner is not None else None
                attrs = dict(mark.attrib) if mark is not None else {}
                self.boundaries[key] = dict(points=pts, marking=attrs)
                boundary_keys[index] = key
            for lid,e in driving.items():
                inner = lid-(1 if lid>0 else -1)
                forward = road.forward(lid)
                # Larger t is left in increasing-s direction.
                left_index, right_index = (lid,inner) if lid>0 else (inner,lid)
                if not forward:
                    left_index,right_index = right_index,left_index
                lk,rk = boundary_keys[left_index],boundary_keys[right_index]
                left,right = [self.boundaries[k]['points'][::1 if forward else -1] for k in (lk,rk)]
                bounds = self.config['bounds']
                if bounds is not None:
                    p = np.vstack([left,right])
                    if p[:,0].max() < bounds[0] or p[:,1].max() < bounds[1] or p[:,0].min() > bounds[2] or p[:,1].min() > bounds[3]:
                        continue
                key = f'road/{road.id}/section/{si}/lane/{lid}/segment/{start:.9f}'
                speed = active(e.findall('speed'),(start+end)/2-a,'sOffset')
                rt = active(road.e.findall('type'),(start+end)/2)
                if speed is None and rt is not None:
                    speed = rt.find('speed')
                value = None
                if speed is not None:
                    try:
                        value = speed_mps(speed.get('max'),speed.get('unit','m/s'))
                    except ValueError as ex:
                        self.diagnostics.add('speed_unit',key,str(ex),'regulatory')
                center = (left+right)/2
                turn = None
                if road.e.get('junction','-1') != '-1':
                    u,v = center[1]-center[0],center[-1]-center[-2]
                    angle = math.atan2(u[0]*v[1]-u[1]*v[0],np.dot(u[:2],v[:2]))
                    turn = 'left' if angle > .35 else 'right' if angle < -.35 else 'straight'
                self.lanes[key] = Lane(key,road.id,si,lid,start,end,forward,lk,rk,left,right,ss,value,turn)

    def _connect(self):
        self._index = {}
        for lane in self.lanes.values():
            self._index.setdefault((lane.road,lane.section,lane.lane_id),[]).append(lane)
        for values in self._index.values():
            values.sort(key=lambda lane:lane.start)
        for lane in self.lanes.values():
            road = self.roads[lane.road]
            group = self._index[lane.road,lane.section,lane.lane_id]
            i = group.index(lane)
            j = i+(1 if lane.forward else -1)
            if 0 <= j < len(group):
                other = group[j]
                if abs((lane.end if lane.forward else lane.start)-(other.start if lane.forward else other.end)) < 1e-6:
                    lane.successors.add(other.key)
                continue
            # Region selection can intentionally cut a road before its actual endpoint.
            secstart = number(road.sections[lane.section],'s')
            secend = number(road.sections[lane.section+1],'s') if lane.section+1<len(road.sections) else road.length
            if abs((lane.end if lane.forward else lane.start)-(secend if lane.forward else secstart)) > 1e-6:
                continue
            kind = 'successor' if lane.forward else 'predecessor'
            link = road.lane_elements(lane.section)[lane.lane_id].find('link/'+kind)
            si = lane.section+(1 if lane.forward else -1)
            if 0 <= si < len(road.sections):
                if link is not None:
                    self._edge(lane,road.id,si,int(link.get('id')), 'start' if lane.forward else 'end')
            else:
                rlink = road.e.find('link/'+kind)
                if rlink is not None and rlink.get('elementType') == 'road' and link is not None:
                    rid = rlink.get('elementId'); contact = rlink.get('contactPoint')
                    if rid not in self.roads or contact not in ('start','end'):
                        self.diagnostics.add('dangling_road_link',lane.key,f'Invalid road link to {rid}, {contact}')
                    else:
                        target = self.roads[rid]
                        self._edge(lane,rid,0 if contact=='start' else len(target.sections)-1,int(link.get('id')),contact)
        for junction in self.root.findall('junction'):
            if junction.get('type') in ('direct','virtual'):
                self.diagnostics.add('junction_type',junction.get('id'),'Direct/virtual junction semantics require review')
            for conn in junction.findall('connection'):
                incoming = self.roads.get(conn.get('incomingRoad'))
                target = self.roads.get(conn.get('connectingRoad'))
                if incoming is None or target is None:
                    self.diagnostics.add('junction_reference',junction.get('id'),'Missing incoming/connecting road')
                    continue
                for link in conn.findall('laneLink'):
                    lid = int(link.get('from')); forward = incoming.forward(lid)
                    group = self._index.get((incoming.id,len(incoming.sections)-1 if forward else 0,lid),[])
                    if not group:
                        continue
                    lane = group[-1] if forward else group[0]
                    contact = conn.get('contactPoint')
                    if contact not in ('start','end'):
                        self.diagnostics.add('junction_contact',junction.get('id'),'Missing/invalid contactPoint')
                        continue
                    self._edge(lane,target.id,0 if contact=='start' else len(target.sections)-1,int(link.get('to')),contact)

    def _edge(self, lane, road, section, lid, contact):
        group = self._index.get((road,section,lid),[])
        if not group:
            # A non-driving destination or an explicitly cropped destination is not a routing edge.
            if self.config['bounds'] is None:
                target = self.roads.get(road)
                if target and lid not in target.lane_elements(section):
                    self.diagnostics.add('dangling_lane_link',lane.key,f'Missing lane {road}/{section}/{lid}')
            return
        target = group[0] if contact=='start' else group[-1]
        if target.forward != (contact=='start'):
            self.diagnostics.add('direction_conflict',lane.key,f'Link enters the exit of {target.key}')
            return
        lane.successors.add(target.key)

    def _controls(self):
        for road in self.roads.values():
            for signal in road.e.findall('signals/signal'):
                key = f'signal/{road.id}/{signal.get("id")}'
                c = dict(source=key, road=road.id, id=signal.get('id'), attributes=dict(signal.attrib),
                         validity=[dict(v.attrib) for v in signal.findall('validity')], lanes=[], kind='unresolved')
                name = signal.get('name','').lower()
                typ = signal.get('type')
                if signal.get('dynamic') == 'yes': c['kind']='traffic_light'
                elif typ=='206' or 'stop' in name: c['kind']='stop'
                elif typ=='205' or 'yield' in name: c['kind']='yield'
                elif typ=='274': c['kind']='speed_limit'
                s = number(signal,'s')
                c['position'] = (road.surface(s,number(signal,'t'))+np.array([0,0,number(signal,'zOffset')])).tolist()
                width = number(signal,'width')
                if width > 0 and abs(number(signal,'pitch')) < 1e-9 and abs(number(signal,'roll')) < 1e-9:
                    _, heading = road.reference(s)
                    heading += number(signal,'hOffset')
                    lateral = np.array([-math.sin(heading),math.cos(heading),0.])
                    center = np.asarray(c['position'])
                    c['geometry'] = [(center+width/2*lateral).tolist(),(center-width/2*lateral).tolist()]

                for lane in self.lanes.values():
                    if lane.road != road.id or not lane.start-1e-6 <= s <= lane.end+1e-6:
                        continue
                    if signal.get('orientation') in ('+','-') and lane.forward != (signal.get('orientation')=='+'):
                        continue
                    if any(int(v.get('fromLane')) <= lane.lane_id <= int(v.get('toLane')) for v in signal.findall('validity')):
                        c['lanes'].append(lane.key)
                self.controls[key] = c
            for obj in road.e.findall('objects/object'):
                if obj.get('type') == 'crosswalk' or 'crosswalk' in obj.get('name','').lower():
                    key = f'object/{road.id}/{obj.get("id")}'
                    self.controls[key] = dict(source=key,road=road.id,id=obj.get('id'),kind='crosswalk',attributes=dict(obj.attrib),lanes=[],
                                              outlines=[ET.tostring(o,encoding='unicode') for o in obj.findall('outlines/outline')+obj.findall('outline')])
                    control = self.controls[key]
                    s, t = number(obj, 's'), number(obj, 't')
                    control['position'] = road.surface(s, t).tolist()
                    # A rectangular crosswalk supplies longitudinal length and
                    # lateral pedestrian crossing width in its object frame.
                    length, width = number(obj, 'length'), number(obj, 'width')
                    if length > 0 and width > 0 and not control['outlines'] and abs(number(obj,'pitch')) < 1e-9 and abs(number(obj,'roll')) < 1e-9:
                        h = number(obj,'hdg')
                        points = []
                        for u,v in [(-length/2,-width/2),(-length/2,width/2),(length/2,width/2),(length/2,-width/2)]:
                            ds = math.cos(h)*u-math.sin(h)*v
                            dt = math.sin(h)*u+math.cos(h)*v
                            if not 0 <= s+ds <= road.length: break
                            point = road.surface(s+ds,t+dt)+np.array([0,0,number(obj,'zOffset')])
                            points.append(point.tolist())
                        if len(points)==4:
                            control['geometry']=points
                    # Associations require explicit validity, runtime evidence,
                    # or corrections; overlapping XY polygons are not enough.

        for road in self.roads.values():
            for ref in road.e.findall('signals/signalReference'):
                matches = [c for c in self.controls.values() if c['id']==ref.get('id') and c['source'].startswith('signal/')]
                if len(matches)!=1:
                    self.diagnostics.add('signal_reference',f'{road.id}/{ref.get("id")}', 'Signal reference is absent or ambiguous','regulatory')
                    continue
                s = number(ref,'s')
                for lane in self.lanes.values():
                    if lane.road==road.id and lane.start-1e-6<=s<=lane.end+1e-6 and any(int(v.get('fromLane'))<=lane.lane_id<=int(v.get('toLane')) for v in ref.findall('validity')):
                        matches[0]['lanes'].append(lane.key)
        self.priorities = [dict(junction=j.get('id'),**p.attrib) for j in self.root.findall('junction') for p in j.findall('priority')]
        for priority in self.priorities:
            self.diagnostics.add('junction_priority',priority['junction'],'Road priority requires explicit lane and stop/yield associations','regulatory')

    def corrections(self, path):
        from .common import sha256
        data = yaml.safe_load(Path(path).read_text())
        if not isinstance(data,dict) or type(data.get('version')) is not int or data.get('version') != 1 or data.get('source_fingerprint') != self.fingerprint:
            raise ValueError('Correction version must be 1 and source_fingerprint must match this OpenDRIVE')
        unknown = set(data)-{'version','source_fingerprint','exclude','connections','speed_limits','controls'}
        if unknown: raise ValueError(f'Unknown correction fields: {sorted(unknown)}')
        # Validate all references before applying any mutation.
        def lane(key):
            if key not in self.lanes: raise ValueError(f'Stale or excluded-region lane reference: {key}')
        for key in data.get('exclude',[]): lane(key)
        for fix in data.get('connections',[]):
            if set(fix)!= {'from','to','action'} or fix['action'] not in ('add','remove'): raise ValueError('Connection needs from, to, action:add|remove')
            lane(fix['from']); lane(fix['to'])
        for key,value in data.get('speed_limits',{}).items():
            lane(key); speed_mps(value['value'],value['unit'])
        for key,fix in data.get('controls',{}).items():
            if key not in self.controls: raise ValueError(f'Stale control reference: {key}')
            if set(fix)-{'kind','lanes','stop_line','geometry','bulbs','speed','yield_lanes','right_of_way_lanes','exclude','height'}:
                raise ValueError(f'Unknown control correction fields for {key}')
            if fix.get('kind', self.controls[key]['kind']) not in ('traffic_light','stop','yield','speed_limit','crosswalk','unresolved'):
                raise ValueError(f'Unknown control kind for {key}')
            if 'exclude' in fix and not isinstance(fix['exclude'], bool): raise ValueError('Control exclude must be boolean')
            if 'height' in fix and (not math.isfinite(float(fix['height'])) or float(fix['height']) <= 0): raise ValueError('Control height must be positive and finite')
            if 'speed' in fix: speed_mps(fix['speed']['value'], fix['speed']['unit'])
            for k in fix.get('lanes',[])+fix.get('yield_lanes',[])+fix.get('right_of_way_lanes',[]):
                lane(k)
                if k in data.get('exclude',[]): raise ValueError(f'Control association refers to excluded lane {k}')
            for name in ('stop_line','geometry'):
                if name in fix:
                    pts = np.asarray(fix[name],dtype=float)
                    if pts.ndim!=2 or pts.shape[1]!=3 or len(pts)<2 or not np.isfinite(pts).all(): raise ValueError(f'{key}/{name} needs finite XYZ points')
            for bulb in fix.get('bulbs',[]):
                if bulb.get('color') not in ('red','yellow','green') or np.asarray(bulb.get('position')).shape!=(3,) or not np.isfinite(bulb['position']).all(): raise ValueError(f'Invalid bulb in {key}')
        self.correction_hash = sha256(path)
        for fix in data.get('connections',[]):
            successors = self.lanes[fix['from']].successors
            if fix['action']=='add': successors.add(fix['to'])
            else: successors.discard(fix['to'])
        for key,value in data.get('speed_limits',{}).items(): self.lanes[key].speed = speed_mps(value['value'],value['unit'])
        for key,fix in data.get('controls',{}).items(): self.controls[key].update(fix)
        for key in data.get('exclude',[]): del self.lanes[key]
        for lane in self.lanes.values(): lane.successors.intersection_update(self.lanes)
        for control in self.controls.values(): control['lanes'] = sorted(set(control['lanes']) & self.lanes.keys())

    def stations(self):
        stations = []
        # Do not deduplicate by XY: stacked and disconnected surfaces stay separate.
        for lane in sorted(self.lanes.values(),key=lambda x:x.key):
            p = lane.center
            d = np.r_[0.,np.cumsum(np.linalg.norm(np.diff(p,axis=0),axis=1))]
            if d[-1] < 1e-6:
                self.diagnostics.add('zero_length',lane.key,'Lane centerline has zero length')
                continue
            for i,t in enumerate(np.linspace(0,d[-1],max(2,math.ceil(d[-1]/self.config['station_spacing'])+1))):
                xyz = np.array([np.interp(t,d,p[:,j]) for j in range(3)])
                bounds = self.config['bounds']
                if bounds and not (bounds[0]<=xyz[0]<=bounds[2] and bounds[1]<=xyz[1]<=bounds[3]): continue
                tangent = p[min(len(p)-1,np.searchsorted(d,t,side='right'))]-p[max(0,min(len(p)-2,np.searchsorted(d,t,side='right')-1))]
                s = float(np.interp(t,d,lane.samples if lane.forward else lane.samples[::-1]))
                bank = polynomial(self.roads[lane.road].banks,s)*(1 if lane.forward else -1)
                stations.append(dict(id=f'{lane.key}/station/{i}',lane=lane.key,xyz=xyz.tolist(),
                                     yaw=math.degrees(math.atan2(tangent[1],tangent[0])),
                                     pitch=math.degrees(math.atan2(tangent[2],np.linalg.norm(tangent[:2]))),roll=math.degrees(bank)))
        return stations

    def summary(self):
        adjacency = {k:set(v.successors) for k,v in self.lanes.items()}
        for k,values in list(adjacency.items()):
            for v in list(values): adjacency[v].add(k)
        components=[]; remaining=set(self.lanes)
        while remaining:
            stack=[min(remaining)]; component=[]; remaining.remove(stack[0])
            while stack:
                k=stack.pop(); component.append(k)
                for v in adjacency[k] & remaining: remaining.remove(v); stack.append(v)
            components.append(sorted(component))
        return dict(source_fingerprint=self.fingerprint, roads=len(self.roads),lanes=len(self.lanes),
                    expected_edges=sorted([k,v] for k,l in self.lanes.items() for v in l.successors),
                    components=components,controls=self.controls,priorities=self.priorities,
                    lane_details={k:dict(road=l.road,section=l.section,lane_id=l.lane_id,s_start=l.start,s_end=l.end,forward=l.forward,speed_mps=l.speed,turn=l.turn,left_boundary=l.left_key,right_boundary=l.right_key) for k,l in self.lanes.items()},
                    diagnostics=self.diagnostics.items,correction_hash=self.correction_hash)
