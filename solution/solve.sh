#!/bin/sh
set -eu
install -m 0644 /solution/geometry.py /workspace/radial_heat/geometry.py
install -m 0644 /solution/boundary.py /workspace/radial_heat/boundary.py
install -m 0644 /solution/solver.py /workspace/radial_heat/solver.py
