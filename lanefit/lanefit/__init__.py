"""lanefit — measure real lane widths from ego-vehicle LiDAR and write them into OpenDRIVE.

Pipeline stages (in order): audit, extract_trajectory, slam, georeference,
measure_widths, conflate, apply, validate. See README.md and docs/PIPELINE.md.
"""
__version__ = "0.1.0"
