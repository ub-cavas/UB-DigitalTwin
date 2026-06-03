#!/usr/bin/env python3
"""
Post-process a raw CARLA global point cloud (PCD or numpy chunk set) into a cleaned map for Autoware.

Features:
- Load raw ASCII/Binary (uncompressed) PCD
- (Optional) Merge raw chunk .npy files before processing
- Remove statistical outliers
- Ground extraction (simple plane RANSAC) and optional reinsert of ground only / or keep all
- Dynamic-ish cluster removal (size / height based heuristic)
- Voxel downsample
- (Optional) Crop to bounding box
- Save final PCD (ASCII or binary) and metadata JSON

Usage examples:
  python3 post_process_pcd.py --in raw_ascii.pcd --voxel 0.1 --out clean_voxel_0_1.pcd
  python3 post_process_pcd.py --chunks-dir ./raw_chunks --voxel 0.1 --out merged_clean.pcd

Dependencies:
  - open3d
  - numpy

NOTE: This script uses heuristic dynamic removal; refine as needed for your maps.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict

import numpy as np
try:
    import open3d as o3d  # type: ignore
except Exception:
    print("[ERROR] open3d required. pip install open3d", file=sys.stderr)
    raise

@dataclass
class ProcessConfig:
    in_path: Optional[str]
    chunks_dir: Optional[str]
    out_path: str
    voxel: float
    stat_nb: int
    stat_std: float
    ransac_dist: float
    ransac_iters: int
    remove_small_clusters: int
    cluster_eps: float
    cluster_min_points: int
    max_object_height: float
    crop_aabb: Optional[Tuple[float,float,float,float,float,float]]
    keep_ground_only: bool
    keep_non_ground_only: bool
    skip_ground_seg: bool
    cluster_drop_tall: bool
    cluster_drop_flat: bool
    cluster_flat_z_span: float
    radius_nb: int
    radius_dist: float
    save_ground_path: Optional[str]
    save_non_ground_path: Optional[str]
    pcd_format: str
    no_compress: bool
    metadata_path: Optional[str]
    verbose: bool
    progress: bool
    debug_dump_on_error: bool
    pre_voxel: float
    max_chunks: int
    merge_points_limit: int
    force_merge: bool
    stream_voxel: float


def _mem_info() -> Optional[str]:
    try:
        import psutil  # type: ignore
        p = psutil.Process(os.getpid())
        rss = p.memory_info().rss / (1024*1024)
        vm = p.memory_info().vms / (1024*1024)
        return f"RSS={rss:.1f}MB VMS={vm:.1f}MB"
    except Exception:
        return None


def _cloud_stats(pcd: o3d.geometry.PointCloud) -> Dict[str, object]:
    n = len(pcd.points)
    if n == 0:
        return {"points": 0}
    pts = np.asarray(pcd.points)
    mn = pts.min(axis=0).tolist()
    mx = pts.max(axis=0).tolist()
    extent = (pts.max(axis=0) - pts.min(axis=0)).tolist()
    return {"points": int(n), "min": mn, "max": mx, "extent": extent}


def load_input(cfg: ProcessConfig) -> o3d.geometry.PointCloud:
    pcs = []
    if cfg.in_path:
        print(f"[INFO] Loading PCD {cfg.in_path}")
        p = o3d.io.read_point_cloud(cfg.in_path)
        pcs.append(p)
    if cfg.chunks_dir:
        print(f"[INFO] Loading chunk directory {cfg.chunks_dir}")
        all_files = sorted(os.listdir(cfg.chunks_dir))
        npy_files = [f for f in all_files if f.startswith('chunk_') and f.endswith('.npy')]
        print(f"[INFO] Found {len(npy_files)} chunk files")
        total_pts = 0
        if cfg.max_chunks > 0:
            print(f"[INFO] Limiting to first {cfg.max_chunks} chunks for this run")
            npy_files = npy_files[:cfg.max_chunks]
        # Streaming voxel accumulation path
        if cfg.stream_voxel and cfg.stream_voxel > 0:
            print(f"[INFO] Streaming-merge with voxel={cfg.stream_voxel} (centroid per voxel)")
            # accumulator: key=(ix,iy,iz) -> [sumx,sumy,sumz,count]
            acc: Dict[Tuple[int,int,int], List[float]] = {}
            xmin=ymin=zmin=xmax=ymax=zmax=None
            if cfg.crop_aabb is not None:
                xmin,ymin,zmin,xmax,ymax,zmax = cfg.crop_aabb
            for idx, f in enumerate(npy_files, 1):
                if not (f.startswith('chunk_') and f.endswith('.npy')):
                    continue
                fp = os.path.join(cfg.chunks_dir, f)
                try:
                    arr = np.load(fp)
                except Exception as e:
                    print(f"[WARN] Failed to load {fp}: {e}")
                    continue
                if arr.size == 0 or arr.ndim != 2 or arr.shape[1] < 3:
                    print(f"[WARN] Skipping invalid/empty chunk {f} shape={arr.shape}")
                    continue
                pts = arr[:, :3]
                # AABB crop per chunk if provided
                if xmin is not None:
                    m = (
                        (pts[:,0] >= xmin) & (pts[:,0] <= xmax) &
                        (pts[:,1] >= ymin) & (pts[:,1] <= ymax) &
                        (pts[:,2] >= zmin) & (pts[:,2] <= zmax)
                    )
                    pts = pts[m]
                # finite mask
                mfin = np.isfinite(pts).all(axis=1)
                if not mfin.all():
                    pts = pts[mfin]
                if pts.shape[0] == 0:
                    continue
                # per-chunk voxel reduce via unique
                vox = cfg.stream_voxel
                idx_ijk = np.floor(pts / vox).astype(np.int64)
                # obtain unique voxel indices and inverse map
                u, inv = np.unique(idx_ijk, axis=0, return_inverse=True)
                cnt = np.bincount(inv)
                sumx = np.bincount(inv, weights=pts[:,0])
                sumy = np.bincount(inv, weights=pts[:,1])
                sumz = np.bincount(inv, weights=pts[:,2])
                # merge into global accumulator
                for k in range(u.shape[0]):
                    key = (int(u[k,0]), int(u[k,1]), int(u[k,2]))
                    c = float(cnt[k])
                    if key in acc:
                        acc[key][0] += float(sumx[k])
                        acc[key][1] += float(sumy[k])
                        acc[key][2] += float(sumz[k])
                        acc[key][3] += c
                    else:
                        acc[key] = [float(sumx[k]), float(sumy[k]), float(sumz[k]), c]
                total_pts += int(pts.shape[0])
                if cfg.verbose and (idx % 5 == 0 or idx == len(npy_files)):
                    mem = _mem_info()
                    print(f"[DEBUG] Streamed {idx}/{len(npy_files)} chunks, input pts processed={total_pts}, voxels={len(acc)}{' | ' + mem if mem else ''}")
            # build final cloud from voxel centroids
            if len(acc) == 0:
                raise RuntimeError('No points accumulated after streaming-merge')
            keys = list(acc.keys())
            sums = np.array([acc[k][:3] for k in keys], dtype=np.float64)
            counts = np.array([acc[k][3] for k in keys], dtype=np.float64)
            centroids = sums / counts[:,None]
            cloud = o3d.geometry.PointCloud()
            cloud.points = o3d.utility.Vector3dVector(centroids)
            if cfg.verbose:
                print(f"[DEBUG] Streaming-merge produced {centroids.shape[0]} voxel centroids, stats: {_cloud_stats(cloud)}")
            return cloud
        for idx, f in enumerate(npy_files, 1):
            if f.startswith('chunk_') and f.endswith('.npy'):
                fp = os.path.join(cfg.chunks_dir, f)
                try:
                    arr = np.load(fp)
                except Exception as e:
                    print(f"[WARN] Failed to load {fp}: {e}")
                    continue
                if arr.size == 0:
                    print(f"[WARN] Empty chunk {f}, skipping")
                    continue
                if arr.ndim != 2 or arr.shape[1] < 3:
                    print(f"[WARN] Bad shape {arr.shape} in {f}, expected Nx>=3, skipping")
                    continue
                mask = np.isfinite(arr[:, :3]).all(axis=1)
                dropped = int(arr.shape[0] - mask.sum())
                if dropped > 0:
                    print(f"[WARN] Dropping {dropped} NaN/Inf points from {f}")
                arr = arr[mask]
                # Optional pre-voxel per chunk to reduce memory before merge
                if cfg.pre_voxel and cfg.pre_voxel > 0:
                    pc_tmp = o3d.geometry.PointCloud()
                    pc_tmp.points = o3d.utility.Vector3dVector(arr[:, :3])
                    pc_tmp = pc_tmp.voxel_down_sample(cfg.pre_voxel)
                    pts = np.asarray(pc_tmp.points)
                    pcs.append(pc_tmp)
                    total_pts += pts.shape[0]
                    if cfg.verbose:
                        print(f"[DEBUG] Chunk {idx}: pre-voxel {cfg.pre_voxel} reduced to {pts.shape[0]} points")
                else:
                    pc = o3d.geometry.PointCloud()
                    pc.points = o3d.utility.Vector3dVector(arr[:, :3])
                    pcs.append(pc)
                    total_pts += arr.shape[0]
                if cfg.verbose and (idx % 5 == 0 or idx == len(npy_files)):
                    mem = _mem_info()
                    print(f"[DEBUG] Loaded {idx}/{len(npy_files)} files, cumulative points={total_pts}{' | ' + mem if mem else ''}")
    if not pcs:
        raise RuntimeError('No input data loaded (provide --in or --chunks-dir)')
    if len(pcs) == 1:
        cloud = pcs[0]
        if cfg.verbose:
            print(f"[DEBUG] Single cloud stats: {_cloud_stats(cloud)}")
        return cloud
    print(f"[INFO] Merging {len(pcs)} partial clouds")
    est_points = sum(len(p.points) for p in pcs)
    if est_points > cfg.merge_points_limit and not cfg.force_merge:
        approx_gb = est_points * 3 * 8 / (1024**3)
        raise RuntimeError(
            f"Merge would allocate a very large array (~{approx_gb:.1f} GB for {est_points} points). "
            f"Use --pre-voxel to reduce points per chunk, or increase --merge-points-limit / pass --force-merge if you have enough RAM."
        )
    all_pts = np.vstack([np.asarray(p.points) for p in pcs])
    merged = o3d.geometry.PointCloud()
    merged.points = o3d.utility.Vector3dVector(all_pts)
    if cfg.verbose:
        approx_mb = all_pts.shape[0] * 3 * 8 / (1024*1024)
        print(f"[DEBUG] Merged points={all_pts.shape[0]} (~{approx_mb:.1f}MB as float64 xyz) stats: {_cloud_stats(merged)}")
    return merged


def statistical_filter(pcd: o3d.geometry.PointCloud, nb_neighbors: int, std_ratio: float):
    if nb_neighbors <= 0:
        return pcd
    start = time.time()
    cl, ind = pcd.remove_statistical_outlier(nb_neighbors=nb_neighbors, std_ratio=std_ratio)
    print(f"[INFO] Statistical outlier removal kept {len(ind)}/{len(pcd.points)} points in {time.time()-start:.2f}s")
    return cl


def radius_filter(pcd: o3d.geometry.PointCloud, nb_points: int, radius: float):
    if nb_points <= 0 or radius <= 0:
        return pcd
    start = time.time()
    cl, ind = pcd.remove_radius_outlier(nb_points=nb_points, radius=radius)
    print(f"[INFO] Radius outlier removal kept {len(ind)}/{len(pcd.points)} points in {time.time()-start:.2f}s")
    return cl


def extract_ground(pcd: o3d.geometry.PointCloud, distance: float, iters: int):
    if len(pcd.points) == 0:
        return pcd, None, None
    plane_model, inliers = pcd.segment_plane(distance_threshold=distance, ransac_n=3, num_iterations=iters)
    ground = pcd.select_by_index(inliers)
    non_ground = pcd.select_by_index(inliers, invert=True)
    print(f"[INFO] Ground extraction: {len(ground.points)} ground, {len(non_ground.points)} non-ground points")
    return ground, non_ground, plane_model


def cluster_remove(
    pcd: o3d.geometry.PointCloud,
    eps: float,
    min_points: int,
    max_height: float,
    remove_smaller_than: int,
    drop_tall: bool,
    drop_flat: bool,
    flat_z_span: float,
    progress: bool,
):
    if len(pcd.points) == 0:
        return pcd
    start = time.time()
    labels = np.array(pcd.cluster_dbscan(eps=eps, min_points=min_points, print_progress=progress))
    if labels.size == 0:
        return pcd
    max_label = labels.max()
    kept_indices: List[int] = []
    np_points = np.asarray(pcd.points)
    dropped = 0
    cluster_stats: List[Dict[str, float]] = []
    for lbl in range(max_label + 1):
        idx = np.where(labels == lbl)[0]
        if idx.size == 0:
            continue
        if remove_smaller_than > 0 and idx.size < remove_smaller_than:
            dropped += idx.size
            continue
        cluster_pts = np_points[idx]
        z_span = float(cluster_pts[:,2].max() - cluster_pts[:,2].min())
        drop = False
        if drop_tall and z_span > max_height:
            drop = True
        if drop_flat and z_span < flat_z_span:
            drop = True
        if drop:
            dropped += idx.size
            continue
        kept_indices.extend(idx.tolist())
        cluster_stats.append({"label": int(lbl), "size": int(idx.size), "z_span": z_span})
    unique_clusters = int(max_label + 1)
    print(f"[INFO] Cluster filtering kept {len(kept_indices)}/{len(pcd.points)} points (dropped {dropped}); clusters={unique_clusters} in {time.time()-start:.2f}s")
    pcd_out = pcd.select_by_index(kept_indices)
    return pcd_out, cluster_stats


def apply_crop(pcd: o3d.geometry.PointCloud, aabb_tuple):
    if aabb_tuple is None:
        return pcd
    xmin, ymin, zmin, xmax, ymax, zmax = aabb_tuple
    aabb = o3d.geometry.AxisAlignedBoundingBox(min_bound=(xmin, ymin, zmin), max_bound=(xmax, ymax, zmax))
    start = time.time()
    cropped = pcd.crop(aabb)
    print(f"[INFO] Cropping to AABB kept {len(cropped.points)}/{len(pcd.points)} points in {time.time()-start:.2f}s")
    return cropped


def voxel_downsample(pcd: o3d.geometry.PointCloud, voxel: float):
    if voxel <= 0:
        return pcd
    start = time.time()
    ds = pcd.voxel_down_sample(voxel)
    print(f"[INFO] Voxel downsample {voxel} => {len(ds.points)} points (was {len(pcd.points)}) in {time.time()-start:.2f}s")
    return ds


def save_pcd(pcd: o3d.geometry.PointCloud, path: str, fmt: str, compress: bool):
    write_ascii = (fmt == 'ascii')
    ok = o3d.io.write_point_cloud(path, pcd, write_ascii=write_ascii, compressed=False if write_ascii else compress, print_progress=True)
    if not ok:
        raise RuntimeError(f'Failed to write {path}')
    try:
        size_bytes = os.path.getsize(path)
        size_mb = size_bytes / (1024*1024)
        size_str = f"{size_mb:.2f}MB"
    except Exception:
        size_str = "?"
    print(f"[OK] Saved {path} ({'ASCII' if write_ascii else 'Binary'}{' compressed' if (not write_ascii and compress) else ''}) with {len(pcd.points)} points | file size {size_str}")


def parse_aabb(aabb_str: Optional[str]):
    if not aabb_str:
        return None
    parts = [float(x) for x in aabb_str.split(',')]
    if len(parts) != 6:
        raise ValueError('AABB must have 6 comma-separated numbers: xmin,ymin,zmin,xmax,ymax,zmax')
    return tuple(parts)  # type: ignore


def main():
    ap = argparse.ArgumentParser(description='Post-process raw CARLA PCD to cleaned Autoware map')
    ap.add_argument('--in', dest='in_path', help='Input PCD (raw)')
    ap.add_argument('--chunks-dir', help='Directory of raw chunk .npy files (optional)')
    ap.add_argument('--out', dest='out_path', required=True, help='Output cleaned PCD')
    ap.add_argument('--voxel', type=float, default=0.1, help='Final voxel size (<=0 to disable)')
    ap.add_argument('--stat-nb', type=int, default=30, help='Statistical outlier neighbors (0 disable)')
    ap.add_argument('--stat-std', type=float, default=2.0, help='Std ratio for statistical filter')
    ap.add_argument('--ground-dist', type=float, default=0.2, help='RANSAC ground distance threshold (m)')
    ap.add_argument('--ground-iters', type=int, default=150, help='RANSAC iterations')
    ap.add_argument('--keep-ground-only', action='store_true', help='Keep only detected ground points')
    ap.add_argument('--cluster-eps', type=float, default=0.8, help='DBSCAN eps (m) for dynamic-ish cluster heuristics')
    ap.add_argument('--cluster-min', type=int, default=20, help='DBSCAN min points')
    ap.add_argument('--remove-small-clusters', type=int, default=0, help='Drop clusters smaller than this (0 disable)')
    ap.add_argument('--max-object-height', type=float, default=8.0, help='Max height span for cluster filtering heuristic')
    ap.add_argument('--cluster-drop-tall', action='store_true', help='Drop clusters whose z-span exceeds max-object-height')
    ap.add_argument('--cluster-drop-flat', action='store_true', help='Drop very flat clusters (z-span below cluster-flat-z-span)')
    ap.add_argument('--cluster-flat-z-span', type=float, default=0.15, help='Z-span threshold for flat cluster drop')
    ap.add_argument('--radius-nb', type=int, default=0, help='Radius outlier min neighbors (0 disable)')
    ap.add_argument('--radius-dist', type=float, default=0.0, help='Radius outlier distance (m)')
    ap.add_argument('--no-ground-seg', action='store_true', help='Skip ground plane segmentation')
    ap.add_argument('--keep-non-ground-only', action='store_true', help='Keep only non-ground points (requires ground segmentation)')
    ap.add_argument('--save-ground', type=str, help='Optional path to save ground-only PCD')
    ap.add_argument('--save-non-ground', type=str, help='Optional path to save non-ground-only PCD')
    ap.add_argument('--crop-aabb', type=str, help='xmin,ymin,zmin,xmax,ymax,zmax')
    ap.add_argument('--pcd-format', choices=['ascii','binary'], default='ascii')
    ap.add_argument('--compress', action='store_true', help='Allow compression for binary (avoid if tool incompatible)')
    ap.add_argument('--metadata', dest='metadata_path', type=str, help='Write metadata JSON path')
    ap.add_argument('--verbose', action='store_true', help='Verbose debug output')
    ap.add_argument('--progress', action='store_true', help='Show algorithm progress bars (DBSCAN/save)')
    ap.add_argument('--debug-dump-on-error', action='store_true', help='On error, dump last available cloud to debug_last.pcd')
    ap.add_argument('--pre-voxel', type=float, default=0.0, help='Pre-voxelize each chunk before merge (0=disable)')
    ap.add_argument('--max-chunks', type=int, default=0, help='Limit number of chunks for this run (0=all)')
    ap.add_argument('--merge-points-limit', type=int, default=60_000_000, help='Safety limit for merging total points (prevents OOM)')
    ap.add_argument('--force-merge', action='store_true', help='Ignore merge points limit (risk OOM)')
    ap.add_argument('--stream-voxel', type=float, default=0.0, help='Stream chunks through a global voxel accumulator (centroid per voxel). Avoids giant merges. 0=disable')
    args = ap.parse_args()

    cfg = ProcessConfig(
        in_path=args.in_path,
        chunks_dir=args.chunks_dir,
        out_path=args.out_path,
        voxel=args.voxel,
        stat_nb=args.stat_nb,
        stat_std=args.stat_std,
        ransac_dist=args.ground_dist,
        ransac_iters=args.ground_iters,
        remove_small_clusters=args.remove_small_clusters,
        cluster_eps=args.cluster_eps,
        cluster_min_points=args.cluster_min,
        max_object_height=args.max_object_height,
        crop_aabb=parse_aabb(args.crop_aabb),
        keep_ground_only=args.keep_ground_only,
        keep_non_ground_only=args.keep_non_ground_only,
        skip_ground_seg=args.no_ground_seg,
        cluster_drop_tall=args.cluster_drop_tall,
        cluster_drop_flat=args.cluster_drop_flat,
        cluster_flat_z_span=args.cluster_flat_z_span,
        radius_nb=args.radius_nb,
        radius_dist=args.radius_dist,
        save_ground_path=args.save_ground,
        save_non_ground_path=args.save_non_ground,
        pcd_format=args.pcd_format,
        no_compress=not args.compress,
        metadata_path=args.metadata_path,
        verbose=args.verbose,
        progress=args.progress,
        debug_dump_on_error=args.debug_dump_on_error,
        pre_voxel=args.pre_voxel,
        max_chunks=args.max_chunks,
        merge_points_limit=args.merge_points_limit,
        force_merge=args.force_merge,
        stream_voxel=args.stream_voxel,
    )

    step_times: Dict[str, float] = {}
    last_cloud: Optional[o3d.geometry.PointCloud] = None
    try:
        t0 = time.time()
        pcd = load_input(cfg)
        step_times['load'] = time.time() - t0
        original_points = len(pcd.points)
        print(f"[INFO] Loaded input cloud: points={original_points} stats={_cloud_stats(pcd)}")
        mem = _mem_info()
        if mem:
            print(f"[DEBUG] Memory after load: {mem}")
        last_cloud = pcd

        # Early crop to shrink subsequent processing cost
        t = time.time(); pcd = apply_crop(pcd, cfg.crop_aabb); step_times['crop'] = time.time()-t
        print(f"[INFO] After crop: points={len(pcd.points)}")
        last_cloud = pcd

        # Outlier removal (statistical then optional radius)
        print(f"[INFO] Statistical filter: nb={cfg.stat_nb} std={cfg.stat_std}")
        t = time.time(); pcd = statistical_filter(pcd, cfg.stat_nb, cfg.stat_std); step_times['statistical'] = time.time()-t
        print(f"[INFO] Radius filter: nb={cfg.radius_nb} dist={cfg.radius_dist}")
        t = time.time(); pcd = radius_filter(pcd, cfg.radius_nb, cfg.radius_dist); step_times['radius'] = time.time()-t
        print(f"[INFO] After outliers: points={len(pcd.points)} stats={_cloud_stats(pcd)}")
        last_cloud = pcd

        ground = None
        non_ground = None
        plane_model = None
        if cfg.skip_ground_seg:
            print('[INFO] Skipping ground segmentation (--no-ground-seg)')
            if cfg.keep_ground_only or cfg.keep_non_ground_only:
                raise ValueError('Cannot use --keep-ground-only or --keep-non-ground-only with --no-ground-seg')
        else:
            print(f"[INFO] Ground segmentation: dist={cfg.ransac_dist} iters={cfg.ransac_iters}")
            t = time.time(); ground, non_ground, plane_model = extract_ground(pcd, cfg.ransac_dist, cfg.ransac_iters); step_times['ground_seg'] = time.time()-t
            print(f"[INFO] Plane model: {plane_model}")
            if cfg.keep_ground_only:
                pcd = ground
                print(f"[INFO] Keeping ground only: points={len(pcd.points)}")
            elif cfg.keep_non_ground_only:
                pcd = non_ground
                print(f"[INFO] Keeping non-ground only: points={len(pcd.points)}")
            else:
                merged = o3d.geometry.PointCloud()
                if ground is not None and non_ground is not None:
                    all_points = np.vstack([
                        np.asarray(ground.points),
                        np.asarray(non_ground.points)
                    ]) if len(non_ground.points) > 0 else np.asarray(ground.points)
                    merged.points = o3d.utility.Vector3dVector(all_points)
                    pcd = merged
                    print(f"[INFO] Recombined ground+non-ground: points={len(pcd.points)}")
            last_cloud = pcd

        # Optionally save intermediate ground/non-ground clouds
        if cfg.save_ground_path and ground is not None:
            print(f"[INFO] Saving intermediate ground to {cfg.save_ground_path}")
            save_pcd(ground, cfg.save_ground_path, cfg.pcd_format, compress=not cfg.no_compress)
        if cfg.save_non_ground_path and non_ground is not None:
            print(f"[INFO] Saving intermediate non-ground to {cfg.save_non_ground_path}")
            save_pcd(non_ground, cfg.save_non_ground_path, cfg.pcd_format, compress=not cfg.no_compress)

        # Cluster filtering
        cluster_stats: Optional[List[Dict[str, float]]] = None
        if (cfg.remove_small_clusters > 0 or cfg.cluster_min_points > 0):
            print(f"[INFO] Clustering: eps={cfg.cluster_eps} min={cfg.cluster_min_points} remove_small<{cfg.remove_small_clusters} drop_tall={cfg.cluster_drop_tall} drop_flat={cfg.cluster_drop_flat} flat_z={cfg.cluster_flat_z_span}")
            if len(pcd.points) > 5_000_000:
                print(f"[WARN] DBSCAN on {len(pcd.points)} points can be very slow and memory intensive. Consider increasing voxel or disabling clustering.")
            t = time.time();
            pcd, cluster_stats = cluster_remove(
                pcd,
                cfg.cluster_eps,
                cfg.cluster_min_points,
                cfg.max_object_height,
                cfg.remove_small_clusters,
                cfg.cluster_drop_tall,
                cfg.cluster_drop_flat,
                cfg.cluster_flat_z_span,
                cfg.progress,
            ); step_times['cluster'] = time.time()-t
            print(f"[INFO] After clustering: points={len(pcd.points)}")
            last_cloud = pcd

        # Voxel downsample
        print(f"[INFO] Voxel downsample: voxel={cfg.voxel}")
        t = time.time(); pcd = voxel_downsample(pcd, cfg.voxel); step_times['voxel'] = time.time()-t
        print(f"[INFO] After voxel: points={len(pcd.points)} stats={_cloud_stats(pcd)}")
        last_cloud = pcd

        # Save
        t = time.time(); save_pcd(pcd, cfg.out_path, cfg.pcd_format, compress=not cfg.no_compress); step_times['save'] = time.time()-t
    except Exception as e:
        print("[ERROR] Processing failed:", str(e))
        traceback.print_exc()
        if cfg.debug_dump_on_error and last_cloud is not None:
            dbg_path = os.path.join(os.path.dirname(cfg.out_path) or '.', 'debug_last.pcd')
            try:
                print(f"[DEBUG] Dumping last available cloud to {dbg_path}")
                save_pcd(last_cloud, dbg_path, cfg.pcd_format, compress=False)
            except Exception as e2:
                print(f"[WARN] Failed to dump debug cloud: {e2}")
        sys.exit(2)

    if cfg.metadata_path:
        meta = {
            'input_points': original_points,
            'output_points': len(pcd.points),
            'voxel': cfg.voxel,
            'stat_nb': cfg.stat_nb,
            'stat_std': cfg.stat_std,
            'radius_nb': cfg.radius_nb,
            'radius_dist': cfg.radius_dist,
            'ground_plane_model': (plane_model.tolist() if plane_model is not None else None),
            'pcd_format': cfg.pcd_format,
            'compressed': (not cfg.no_compress and cfg.pcd_format == 'binary'),
            'crop_aabb': cfg.crop_aabb,
            'keep_ground_only': cfg.keep_ground_only,
            'keep_non_ground_only': cfg.keep_non_ground_only,
            'skip_ground_seg': cfg.skip_ground_seg,
            'cluster_removed_small_threshold': cfg.remove_small_clusters,
            'cluster_drop_tall': cfg.cluster_drop_tall,
            'cluster_drop_flat': cfg.cluster_drop_flat,
            'cluster_flat_z_span': cfg.cluster_flat_z_span,
            'timings_sec': step_times,
            'cluster_stats': cluster_stats,
        }
        with open(cfg.metadata_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2)
        print(f"[OK] Wrote metadata {cfg.metadata_path}")

if __name__ == '__main__':
    main()
