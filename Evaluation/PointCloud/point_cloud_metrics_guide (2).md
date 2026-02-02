# Point Cloud Comparison Metrics — Collection Guide

This guide covers the collection and interpretation of geometric fidelity metrics between a **twin** (digitally reconstructed) point cloud and a **real** (ground-truth sensor capture) point cloud. The companion script `point_cloud_metrics.py` computes all metrics described here.

---

## Prerequisites

### Environment Setup

Create and activate a dedicated conda environment:

```bash
conda create -n pcmetrics python=3.11 -y
conda activate pcmetrics
pip install numpy scipy open3d scikit-learn
```

All subsequent commands in this guide assume the `pcmetrics` environment is active.

### Data Preparation (CloudCompare)

Before running the evaluation, both point clouds must be co-registered, unit-consistent, and cleaned. The steps below walk through doing this in CloudCompare. Both clouds should be exported in a format Open3D can read (`.ply`, `.pcd`, `.xyz`, `.pts`, etc.).

#### Step 1 — Load Both Clouds

Open CloudCompare and drag in both the twin and real point cloud files (or use **File → Open**). They will appear as separate entities in the **DB Tree** panel on the left.

#### Step 2 — Verify Unit Consistency

The evaluation script assumes both clouds are in **meters**. If your clouds are in different units (e.g., millimeters from a scanner, meters from ROS), rescale before doing anything else:

1. Select the cloud to rescale in the DB Tree.
2. Go to **Edit → Multiply / Scale**.
3. Enter the appropriate scale factor (e.g., `0.001` to convert mm → m) for X, Y, and Z.
4. Repeat for the other cloud if needed.

You can sanity-check units by selecting a cloud and reading the bounding box dimensions in the **Properties** panel — they should make physical sense in meters.

#### Step 3 — Co-Registration (Alignment)

If the two clouds are not already in the same coordinate frame, align them using ICP:

1. Select **both** clouds in the DB Tree (Ctrl+click).
2. Go to **Tools → Registration → Fine Registration (ICP)**.
3. Set the **reference** cloud to the real cloud (this stays fixed) and the **aligned** cloud to the twin.
4. Configure ICP parameters:
   - **Overlap**: estimate what fraction of the twin overlaps the real cloud (e.g., 80%).
   - **Random sampling limit**: 50,000–100,000 points is usually sufficient for convergence.
   - **RMS difference**: set a convergence threshold (e.g., `1e-6`).
   - **Final overlap**: leave at default unless you have reason to change it.
5. Click **OK** and inspect the result. The convergence RMS is printed in the console — this is the residual alignment error you should document.

If the clouds are very far apart or rotated significantly, do a coarse alignment first:

1. Select both clouds.
2. Go to **Tools → Registration → Match Bounding-Box Centers** to roughly center them together.
3. Optionally use **Tools → Registration → Align (Point Pairs Picking)** to manually pick 4+ corresponding point pairs for an initial rigid transform.
4. Then run ICP as above to refine.

#### Step 4 — Cleaning

Remove noise and artifacts that would skew the metrics:

**Statistical Outlier Removal (SOR):**
1. Select a cloud in the DB Tree.
2. Go to **Tools → Clean → SOR Filter**.
3. Set the number of neighbors (e.g., `6`) and the standard deviation multiplier (e.g., `1.0` — lower is more aggressive).
4. Click **OK**. CloudCompare will segment the cloud into inliers and outliers. Delete or hide the outlier subset.
5. Repeat for the other cloud.

**Manual Segmentation** (for ground planes, walls, or regions outside the area of interest):
1. Select the cloud.
2. Use the **Segment** tool (scissors icon in the toolbar, or **Edit → Segment**).
3. Draw a polygon around the region to keep or remove.
4. Confirm the segmentation. Delete the unwanted portion.

**Subsampling** (optional, for very large clouds):
1. Select the cloud.
2. Go to **Edit → Subsample**.
3. Choose a method:
   - **Space**: subsample to a minimum point spacing (e.g., `0.01` m for 1 cm spacing). This is equivalent to voxel downsampling.
   - **Random**: keep a fixed number or percentage of points.
4. Document the subsampling parameters, as they affect all downstream metrics.

#### Step 5 — Export

1. Select the cleaned, aligned cloud in the DB Tree.
2. Go to **File → Save As** and choose `.ply` (binary PLY is recommended for large clouds).
3. Repeat for the other cloud.
4. Place both exported files in the same directory as `point_cloud_metrics.py`.

---

## Running the Evaluation

```bash
# Basic usage
python point_cloud_metrics.py --twin twin.ply --real real.ply

# Custom thresholds and export to JSON + CSV
python point_cloud_metrics.py \
    --twin twin.ply \
    --real real.ply \
    --fscore-thresholds 0.01 0.02 0.05 0.10 0.20 \
    --voxel-resolutions 0.05 0.10 0.25 0.50 \
    --output-json results.json \
    --output-csv results.csv
```

| Argument | Default | Description |
|----------|---------|-------------|
| `--twin` | *(required)* | Path to the twin point cloud file |
| `--real` | *(required)* | Path to the real point cloud file |
| `--fscore-thresholds` | `0.02 0.05 0.10` | F-score distance thresholds in meters |
| `--voxel-resolutions` | `0.05 0.10 0.25` | Voxel grid resolutions in meters |
| `--output-json` | *(none)* | Path to save results as a JSON file |
| `--output-csv` | *(none)* | Path to save results as a CSV file |

---

## Metric Definitions and Interpretation

All metrics are built on top of **nearest-neighbor (NN) distances**: for every point in cloud A, find the distance to the closest point in cloud B. The script computes these in both directions — twin→real and real→twin — since they measure different things.

- **Twin→Real** distances measure **accuracy**: are the twin's points actually near the real surface?
- **Real→Twin** distances measure **completeness**: does the twin cover the entire real surface?

### 1 · Cloud-to-Cloud Distances

| Metric | Definition | What It Reveals |
|--------|-----------|-----------------|
| **Mean distance** | Average NN distance | Overall average error across the cloud |
| **RMS distance** | Root-mean-square of NN distances | Average error with heavier penalty on large deviations |
| **Hausdorff distance** | Maximum NN distance | Worst-case error anywhere in the cloud |
| **Symmetric** variant | Combines both directions (mean of means, max of maxes) | Single-number summary accounting for both accuracy and completeness |

The script also reports **percentile distances** (P90, P95, P99) as robust alternatives to the Hausdorff max, which is extremely sensitive to single outlier points — especially relevant for noisy LiDAR data.

Lower values are better for all C2C metrics.

### 2 · F-Score at Distance Thresholds

Given a distance threshold τ, the F-score treats reconstruction as a retrieval problem:

- **Precision(τ)**: fraction of twin points within τ of the real surface.
- **Recall(τ)**: fraction of real points within τ of the twin surface.
- **F1(τ)**: harmonic mean of precision and recall.

#### Recommended Thresholds

| Threshold | Typical Use |
|-----------|-------------|
| τ = 2 cm | Fine detail — edge quality, small geometric errors |
| τ = 5 cm | Medium tolerance — typical for indoor scene reconstruction |
| τ = 10 cm | Coarse tolerance — large-scale structural agreement |

#### Reading the Results

- **High precision, low recall** → the twin is accurate where it exists but is missing regions (holes, incomplete coverage).
- **Low precision, high recall** → the twin covers the real surface well but includes spurious geometry (phantom points, noise).
- **F1@2cm low but F1@10cm ≈ 1.0** → the twin has the right overall shape but lacks fine detail.

### 3 · Voxel Occupancy Metrics

Both clouds are discretized onto a regular 3D grid. Each voxel is marked as occupied or empty, producing binary occupancy sets V_twin and V_real.

| Metric | Definition | What It Reveals |
|--------|-----------|-----------------|
| **Voxel IoU** | \|V_twin ∩ V_real\| / \|V_twin ∪ V_real\| | Overall volumetric agreement |
| **Voxel Precision** | \|V_twin ∩ V_real\| / \|V_twin\| | Fraction of twin voxels that overlap with real (hallucinated geometry if < 1) |
| **Voxel Recall** | \|V_twin ∩ V_real\| / \|V_real\| | Fraction of real voxels covered by the twin (missing regions if < 1) |

#### Recommended Resolutions

| Resolution | Use Case |
|------------|----------|
| 5 cm | Fine structural detail, small objects |
| 10 cm | General-purpose scene comparison |
| 25 cm | Large-scale structural agreement |
| 50 cm | Coarse occupancy sanity check |

#### Key Properties

Voxel metrics are **density-invariant**: a voxel is occupied or not regardless of how many points fall inside it. This makes them robust to differences in point density between the twin and real clouds (e.g., LiDAR returns are denser at close range). However, coarser voxel grids inflate IoU by merging nearby-but-distinct surfaces into the same cell, so always report at multiple resolutions.

---

## Scalability Notes

The nearest-neighbor query dominates runtime. Approximate expectations on a modern CPU:

| Point Count | NN Query Time | Voxel Time |
|-------------|---------------|------------|
| 100K | < 1s | < 0.1s |
| 1M | ~5s | < 0.5s |
| 10M | ~60s | ~3s |
| 50M | ~5 min | ~15s |

For very large clouds, consider voxel-downsampling both inputs before running the evaluation. Document any subsampling strategy, as it affects all downstream metrics.

---

## Reporting Recommendations

When publishing or documenting results, include:

1. **Cloud metadata** — point counts for both twin and real, file formats, any preprocessing applied (subsampling, filtering, cropping).
2. **Registration method** — how alignment was achieved and any residual alignment error.
3. **All three metric families** — C2C distances capture average and worst-case error, F-scores capture the accuracy/completeness tradeoff at meaningful scales, and voxel IoU provides a density-invariant volumetric summary.
4. **Multiple thresholds/resolutions** — a single number never tells the full story.
5. **Units** — always state whether values are in meters, centimeters, or millimeters.
6. **Error distributions** — consider including histograms of NN distances alongside scalar summaries to reveal multimodal error patterns.
