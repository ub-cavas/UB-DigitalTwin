#!/usr/bin/env python3
"""
point_cloud_metrics.py

Compute geometric fidelity metrics between a twin and a real point cloud.

Usage:
    python point_cloud_metrics.py --twin twin.ply --real real.ply
"""

import argparse
import csv
import json
import time

import numpy as np
import open3d as o3d
from scipy.spatial import cKDTree


# ── Loading ──────────────────────────────────────────────────────────────────

def load_cloud(path: str) -> np.ndarray:
    pcd = o3d.io.read_point_cloud(path)
    pts = np.asarray(pcd.points)
    if pts.shape[0] == 0:
        raise ValueError(f"Empty point cloud: {path}")
    return pts


# ── Nearest Neighbor ─────────────────────────────────────────────────────────

def nn_distances(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    tree = cKDTree(target)
    dists, _ = tree.query(source, k=1)
    return dists


# ── Cloud-to-Cloud ───────────────────────────────────────────────────────────

def cloud_to_cloud_metrics(d_t2r: np.ndarray, d_r2t: np.ndarray) -> dict:
    return {
        "mean_twin2real": float(np.mean(d_t2r)),
        "mean_real2twin": float(np.mean(d_r2t)),
        "mean_symmetric": float((np.mean(d_t2r) + np.mean(d_r2t)) / 2),
        "rms_twin2real": float(np.sqrt(np.mean(d_t2r**2))),
        "rms_real2twin": float(np.sqrt(np.mean(d_r2t**2))),
        "rms_symmetric": float(np.sqrt((np.mean(d_t2r**2) + np.mean(d_r2t**2)) / 2)),
        "hausdorff_twin2real": float(np.max(d_t2r)),
        "hausdorff_real2twin": float(np.max(d_r2t)),
        "hausdorff_symmetric": float(max(np.max(d_t2r), np.max(d_r2t))),
        "p90_twin2real": float(np.percentile(d_t2r, 90)),
        "p95_twin2real": float(np.percentile(d_t2r, 95)),
        "p99_twin2real": float(np.percentile(d_t2r, 99)),
        "p90_real2twin": float(np.percentile(d_r2t, 90)),
        "p95_real2twin": float(np.percentile(d_r2t, 95)),
        "p99_real2twin": float(np.percentile(d_r2t, 99)),
    }


# ── F-Score ──────────────────────────────────────────────────────────────────

def fscore(d_t2r: np.ndarray, d_r2t: np.ndarray, tau: float) -> dict:
    prec = float(np.mean(d_t2r < tau))
    rec  = float(np.mean(d_r2t < tau))
    f1   = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
    return {"threshold": tau, "precision": prec, "recall": rec, "f1": f1}


# ── Voxel Metrics ────────────────────────────────────────────────────────────

def voxelize(points: np.ndarray, voxel_size: float) -> set:
    indices = np.floor(points / voxel_size).astype(np.int64)
    return set(map(tuple, indices))


def voxel_metrics(V_twin: set, V_real: set) -> dict:
    inter = V_twin & V_real
    union = V_twin | V_real
    n_i, n_u = len(inter), len(union)
    n_t, n_r = len(V_twin), len(V_real)
    iou  = n_i / n_u if n_u > 0 else 0.0
    prec = n_i / n_t if n_t > 0 else 0.0
    rec  = n_i / n_r if n_r > 0 else 0.0
    f1   = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
    return {
        "iou": iou, "precision": prec, "recall": rec, "f1": f1,
        "n_twin": n_t, "n_real": n_r,
        "n_intersection": n_i, "n_union": n_u,
    }


# ── CSV Export ───────────────────────────────────────────────────────────────

def write_csv(results: dict, path: str):
    """
    Write all metrics to a flat CSV with columns: category, metric, value.
    """
    rows = []

    # Cloud-to-cloud
    c2c = results["cloud_to_cloud"]
    for key, val in c2c.items():
        rows.append(("cloud_to_cloud", key, f"{val:.8f}"))

    # F-score
    for entry in results["fscore"]:
        tau_cm = f"{entry['threshold'] * 100:.0f}cm"
        rows.append(("fscore", f"precision@{tau_cm}", f"{entry['precision']:.6f}"))
        rows.append(("fscore", f"recall@{tau_cm}",    f"{entry['recall']:.6f}"))
        rows.append(("fscore", f"f1@{tau_cm}",        f"{entry['f1']:.6f}"))

    # Voxel
    for entry in results["voxel"]:
        r_cm = f"{entry['resolution'] * 100:.0f}cm"
        rows.append(("voxel", f"iou@{r_cm}",            f"{entry['iou']:.6f}"))
        rows.append(("voxel", f"precision@{r_cm}",      f"{entry['precision']:.6f}"))
        rows.append(("voxel", f"recall@{r_cm}",         f"{entry['recall']:.6f}"))
        rows.append(("voxel", f"f1@{r_cm}",             f"{entry['f1']:.6f}"))
        rows.append(("voxel", f"n_twin@{r_cm}",         str(entry['n_twin'])))
        rows.append(("voxel", f"n_real@{r_cm}",         str(entry['n_real'])))
        rows.append(("voxel", f"n_intersection@{r_cm}", str(entry['n_intersection'])))
        rows.append(("voxel", f"n_union@{r_cm}",        str(entry['n_union'])))

    with open(path, "w", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(["category", "metric", "value"])
        writer.writerows(rows)


# ── Main ─────────────────────────────────────────────────────────────────────

def evaluate(twin_path: str, real_path: str,
             fscore_thresholds: list[float] = [0.02, 0.05, 0.10],
             voxel_resolutions: list[float] = [0.05, 0.10, 0.25],
             output_json: str | None = None,
             output_csv: str | None = None) -> dict:
    """Run all metrics and return a results dictionary."""

    print(f"Loading twin cloud: {twin_path}")
    P_twin = load_cloud(twin_path)
    print(f"  → {P_twin.shape[0]:,} points")

    print(f"Loading real cloud: {real_path}")
    P_real = load_cloud(real_path)
    print(f"  → {P_real.shape[0]:,} points\n")

    # ── Nearest-neighbor distances ──
    t0 = time.perf_counter()
    print("Computing nearest-neighbor distances (twin → real)...")
    d_t2r = nn_distances(P_twin, P_real)
    print("Computing nearest-neighbor distances (real → twin)...")
    d_r2t = nn_distances(P_real, P_twin)
    print(f"  NN queries completed in {time.perf_counter() - t0:.2f}s\n")

    results = {}

    # ── C2C ──
    results["cloud_to_cloud"] = cloud_to_cloud_metrics(d_t2r, d_r2t)

    # ── F-Score ──
    results["fscore"] = [fscore(d_t2r, d_r2t, tau) for tau in fscore_thresholds]

    # ── Voxel ──
    results["voxel"] = []
    for r in voxel_resolutions:
        V_twin = voxelize(P_twin, r)
        V_real = voxelize(P_real, r)
        vm = voxel_metrics(V_twin, V_real)
        vm["resolution"] = r
        results["voxel"].append(vm)

    # ── Print ──
    print("=" * 70)
    print("  POINT CLOUD COMPARISON RESULTS")
    print("=" * 70)

    c2c = results["cloud_to_cloud"]
    print("\n── Cloud-to-Cloud Distances ──")
    print(f"  {'':28s} {'Twin→Real':>12s} {'Real→Twin':>12s} {'Symmetric':>12s}")
    print(f"  {'Mean (m)':<28s} {c2c['mean_twin2real']:>12.6f} {c2c['mean_real2twin']:>12.6f} {c2c['mean_symmetric']:>12.6f}")
    print(f"  {'RMS (m)':<28s} {c2c['rms_twin2real']:>12.6f} {c2c['rms_real2twin']:>12.6f} {c2c['rms_symmetric']:>12.6f}")
    print(f"  {'Hausdorff (m)':<28s} {c2c['hausdorff_twin2real']:>12.6f} {c2c['hausdorff_real2twin']:>12.6f} {c2c['hausdorff_symmetric']:>12.6f}")
    print(f"  {'P90 (m)':<28s} {c2c['p90_twin2real']:>12.6f} {c2c['p90_real2twin']:>12.6f}")
    print(f"  {'P95 (m)':<28s} {c2c['p95_twin2real']:>12.6f} {c2c['p95_real2twin']:>12.6f}")
    print(f"  {'P99 (m)':<28s} {c2c['p99_twin2real']:>12.6f} {c2c['p99_real2twin']:>12.6f}")

    print("\n── F-Score ──")
    print(f"  {'Threshold':<14s} {'Precision':>10s} {'Recall':>10s} {'F1':>10s}")
    for f in results["fscore"]:
        print(f"  {'τ = '+str(int(f['threshold']*100))+' cm':<14s} {f['precision']:>10.4f} {f['recall']:>10.4f} {f['f1']:>10.4f}")

    print("\n── Voxel Occupancy ──")
    print(f"  {'Resolution':<14s} {'IoU':>8s} {'Prec':>8s} {'Recall':>8s} {'F1':>8s} {'|V_t|':>10s} {'|V_r|':>10s}")
    for v in results["voxel"]:
        label = f"r = {int(v['resolution']*100)} cm"
        print(f"  {label:<14s} {v['iou']:>8.4f} {v['precision']:>8.4f} {v['recall']:>8.4f} {v['f1']:>8.4f} {v['n_twin']:>10d} {v['n_real']:>10d}")

    print()

    # ── Save JSON ──
    if output_json:
        with open(output_json, "w") as fp:
            json.dump(results, fp, indent=2)
        print(f"Results saved to {output_json}")

    # ── Save CSV ──
    if output_csv:
        write_csv(results, output_csv)
        print(f"Results saved to {output_csv}")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Point cloud comparison metrics")
    parser.add_argument("--twin", required=True, help="Path to twin point cloud")
    parser.add_argument("--real", required=True, help="Path to real point cloud")
    parser.add_argument("--fscore-thresholds", nargs="+", type=float,
                        default=[0.02, 0.05, 0.10],
                        help="F-score distance thresholds in meters")
    parser.add_argument("--voxel-resolutions", nargs="+", type=float,
                        default=[0.05, 0.10, 0.25],
                        help="Voxel grid resolutions in meters")
    parser.add_argument("--output-json", default=None,
                        help="Path to save results as JSON")
    parser.add_argument("--output-csv", default=None,
                        help="Path to save results as CSV")
    args = parser.parse_args()

    evaluate(
        twin_path=args.twin,
        real_path=args.real,
        fscore_thresholds=args.fscore_thresholds,
        voxel_resolutions=args.voxel_resolutions,
        output_json=args.output_json,
        output_csv=args.output_csv,
    )
