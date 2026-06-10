#!/bin/bash
# ========================================
# CARLA Python Dependencies Installer
# ========================================

echo "🚀 Installing CARLA (0.9.16) and transforms3d..."

# Install CARLA and transforms3d
python3 -m pip install carla==0.9.16
pip3 install --upgrade transforms3d

# Verification step
echo "----------------------------------------"
echo "✅ Installed Python packages:"
python3 -m pip show carla transforms3d | grep -E "Name:|Version:"
echo "----------------------------------------"
echo "✅ Installation complete."
echo "========================================"

