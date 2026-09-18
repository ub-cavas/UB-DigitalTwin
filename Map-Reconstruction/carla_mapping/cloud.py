"""Transactional disk-backed voxel partitions and bounded-memory PCD export.

Each station is a SQLite transaction: its voxels and completion record commit
or roll back together. SQLite's journal also covers ENOSPC and process death.
"""
from collections import deque
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import numpy as np
import yaml
from .common import atomic_write, sha256, write_json

SEMANTIC = np.dtype([('x','<f4'),('y','<f4'),('z','<f4'),('cosine','<f4'),('object','<u4'),('label','<u4')])
DYNAMIC_LABELS = (12,13,14,15,16,17,18,19,21)


def measurement_points(measurement):
    data=np.frombuffer(measurement.raw_data,dtype=SEMANTIC)
    keep=~np.isin(data['label'],DYNAMIC_LABELS)
    xyz=np.column_stack([data[k][keep] for k in ('x','y','z')]).astype(np.float64)
    xyz=xyz[np.isfinite(xyz).all(axis=1)]
    distance=np.linalg.norm(xyz,axis=1); valid=distance>.5
    xyz,distance=xyz[valid],distance[valid]
    matrix=np.asarray(measurement.transform.get_matrix(),dtype=np.float64)
    world=xyz@matrix[:3,:3].T+matrix[:3,3]; world[:,1]*=-1
    points=np.column_stack([world,np.exp(-.004*distance)]).astype('<f4')
    labels,counts=np.unique(data['label'],return_counts=True)
    return points,dict(zip(map(int,labels),map(int,counts))),int((~keep).sum())


def pcd_header(count):
    return ('# .PCD v0.7\nVERSION 0.7\nFIELDS x y z intensity\nSIZE 4 4 4 4\nTYPE F F F F\nCOUNT 1 1 1 1\n'
            f'WIDTH {count}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {count}\nDATA binary\n').encode()


def read_pcd(path):
    with Path(path).open('rb') as f:
        header={}
        for _ in range(64):
            raw=f.readline(4096)
            if not raw: raise ValueError(f'Missing PCD DATA header: {path}')
            line=raw.decode('ascii').strip()
            if line and not line.startswith('#'):
                k,*v=line.split(); header[k]=v
                if k=='DATA': break
        else: raise ValueError('PCD header too long')
        offset=f.tell()
    if header.get('FIELDS')!=['x','y','z','intensity'] or header.get('SIZE')!=['4']*4 or header.get('TYPE')!=['F']*4 or header.get('COUNT')!=['1']*4 or header.get('DATA')!=['binary']:
        raise ValueError('Expected uncompressed binary float32 XYZI PCD')
    n=int(header['POINTS'][0])
    if n<0 or int(header['WIDTH'][0])*int(header['HEIGHT'][0])!=n or Path(path).stat().st_size!=offset+n*16:
        raise ValueError('PCD dimensions/payload do not match header')
    return np.memmap(path,dtype='<f4',mode='r',offset=offset,shape=(n,4)) if n else np.empty((0,4),dtype='<f4')


class VoxelStore:
    def __init__(self, directory, identity, config, resume=False):
        self.directory=Path(directory); self.directory.mkdir(parents=True,exist_ok=True)
        self.path=self.directory/'capture.sqlite3'
        existed=self.path.exists()
        if existed and not resume: raise ValueError('Capture exists: use --resume with the same source and configuration')
        if resume and not existed: raise ValueError('No capture checkpoint to resume')
        self.config=config
        # A bounded cache of confirmed voxels avoids repeated SQLite lookups
        # in overlapping scans. Cache misses always fall through to SQLite.
        self._known = set()
        self._known_order = deque()
        self._known_limit = max(1, int(config['memory_mib']*1024**2*.20/128))
        self.db=sqlite3.connect(self.path,timeout=30)
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA temp_store=FILE')
        self.db.execute(f'PRAGMA cache_size=-{int(config["memory_mib"]*1024/4)}')
        try:
            if existed:
                if self.db.execute('PRAGMA quick_check').fetchone()[0]!='ok': raise ValueError('Damaged capture checkpoint')
                previous=json.loads(self.db.execute('SELECT value FROM metadata WHERE key="identity"').fetchone()[0])
                if previous!=identity: raise ValueError('Incompatible resume: source, corrections, stations, or configuration changed')
            else:
                with self.db:
                    self.db.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
                    self.db.execute('CREATE TABLE stations(id TEXT PRIMARY KEY,details TEXT NOT NULL)')
                    self.db.execute('CREATE TABLE voxels(ix INTEGER,iy INTEGER,iz INTEGER,tx INTEGER,ty INTEGER,x REAL,y REAL,z REAL,intensity REAL,PRIMARY KEY(ix,iy,iz)) WITHOUT ROWID')
                    self.db.execute('CREATE INDEX tiles ON voxels(tx,ty)')
                    self.db.execute('INSERT INTO metadata VALUES (?,?)',('identity',json.dumps(identity,sort_keys=True)))
        except BaseException:
            self.db.close(); raise

    def completed(self):
        return {r[0] for r in self.db.execute('SELECT id FROM stations')}

    def commit_station(self, station_id, sweeps, details):
        if self.db.execute('SELECT 1 FROM stations WHERE id=?',(station_id,)).fetchone(): return False
        voxel=self.config['voxel']; tile=self.config['tile_size']
        confirmed = []
        with self.db:
            for points in sweeps:
                for start in range(0,len(points),16384):
                    block=np.asarray(points[start:start+16384],dtype='<f4')
                    if block.ndim!=2 or block.shape[1]!=4 or not np.isfinite(block).all(): raise ValueError('Nonfinite or malformed point data')
                    if np.any(np.abs(np.spacing(block[:,:3])) > voxel/2): raise ValueError('Coordinates exceed float32 precision for requested voxel size; no recentering is performed')
                    cells=np.floor(block[:,:3].astype(np.float64)/voxel)
                    if np.any(np.abs(cells)>=2**62): raise ValueError('Voxel coordinates exceed signed integer limits')
                    cells = cells.astype(np.int64)
                    # Keep the same first actual return as INSERT OR IGNORE.
                    # Exact packed keys are only used inside their safe range;
                    # larger coordinates retain the general three-integer path.
                    limit = 1 << 20
                    if np.all(cells >= -limit) and np.all(cells < limit):
                        biased = cells + limit
                        keys = (biased[:,0] << 42) | (biased[:,1] << 21) | biased[:,2]
                        _, first = np.unique(keys, return_index=True)
                        block, cells, keys = block[first], cells[first], keys[first]
                        missing = np.fromiter((int(k) not in self._known for k in keys), dtype=bool, count=len(keys))
                        block, cells, keys = block[missing], cells[missing], keys[missing]
                        confirmed.append(keys)
                    tiles=np.floor(block[:,:2].astype(np.float64)/tile)
                    rows=((int(c[0]),int(c[1]),int(c[2]),int(t[0]),int(t[1]),float(p[0]),float(p[1]),float(p[2]),float(p[3])) for p,c,t in zip(block,cells,tiles))
                    self.db.executemany('INSERT OR IGNORE INTO voxels VALUES (?,?,?,?,?,?,?,?,?)',rows)
            self.db.execute('INSERT INTO stations VALUES (?,?)',(station_id,json.dumps(details,sort_keys=True)))
        # Only committed transactions can populate the cache. A failed station
        # must be able to insert its points on the next attempt.
        for keys in confirmed:
            for value in keys:
                key = int(value)
                if key not in self._known:
                    if len(self._known) >= self._known_limit:
                        self._known.remove(self._known_order.popleft())
                    self._known.add(key)
                    self._known_order.append(key)
        return True

    def count(self): return self.db.execute('SELECT count(*) FROM voxels').fetchone()[0]

    def _export_file(self,path,where='',args=()):
        count=self.db.execute('SELECT count(*) FROM voxels '+where,args).fetchone()[0]
        path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
        fd,temp=tempfile.mkstemp(prefix='.'+path.name,dir=path.parent)
        try:
            with os.fdopen(fd,'wb') as f:
                f.write(pcd_header(count))
                cur=self.db.execute('SELECT x,y,z,intensity FROM voxels '+where+' ORDER BY ix,iy,iz',args)
                while True:
                    rows=cur.fetchmany(16384)
                    if not rows: break
                    np.asarray(rows,dtype='<f4').tofile(f)
                f.flush(); os.fsync(f.fileno())
            os.replace(temp,path)
        finally:
            if os.path.exists(temp): os.unlink(temp)
        return dict(path=str(path.relative_to(self.directory.parent)),points=count,sha256=sha256(path))

    def export(self,output,mode=None):
        output=Path(output); mode=mode or self.config['export']; files=[]
        target=output/'pointcloud_map.pcd'
        if (target.is_file() and mode=='tiled') or (target.is_dir() and mode=='single'):
            raise ValueError('Export type conflicts with existing output')
        if mode=='single': files.append(self._export_file(target))
        else:
            target.mkdir(parents=True,exist_ok=True)
            size=int(self.config['tile_size']); metadata=dict(x_resolution=size,y_resolution=size)
            for tx,ty in self.db.execute('SELECT DISTINCT tx,ty FROM voxels ORDER BY tx,ty'):
                name=f'tile_{tx}_{ty}.pcd'
                files.append(self._export_file(target/name,'WHERE tx=? AND ty=?',(tx,ty)))
                metadata[name]=[tx*size,ty*size]
            atomic_write(output/'pointcloud_map_metadata.yaml',yaml.safe_dump(metadata,sort_keys=True))
        return files

    def close(self): self.db.close()
