#!/bin/bash
# Offline artifact target only: never enumerate, reset, read or flash a device.
set -euo pipefail

if [[ "$#" != 0 || ! -d /output || -z "${BM83_BUILDER_IMAGE:-}" ]]; then
  echo 'Use the documented immutable builder with an empty /output mount and BM83_BUILDER_IMAGE.' >&2
  exit 2
fi
if [[ -n "$(find /output -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  echo '/output must be empty; previous outputs are never overwritten.' >&2
  exit 2
fi
if [[ -e /opt/circuitpython/mpy-cross/build || -e /opt/circuitpython/ports/espressif/build-espressif_esp32s3_devkitc_1_n8r8 ]]; then
  echo 'A fresh builder container with no previous object directories is required.' >&2
  exit 2
fi

export SOURCE_DATE_EPOCH
SOURCE_DATE_EPOCH="$(git -C /opt/circuitpython show -s --format=%ct HEAD)"
export PATH="/opt/idf-venv/bin:/opt/host-venv/bin:$PATH"
export CMAKE_BUILD_PARALLEL_LEVEL=4
idf_source=/opt/circuitpython/ports/espressif/esp-idf

echo 'CHECK: pinned source, Python dependencies, and synthetic crypto tools'
python /opt/recipe/record-build.py --check-sources
python -m pip check
python /opt/recipe/verify_host_tools.py > /output/host-tools.json
python "$idf_source/tools/check_python_dependencies.py" --requirements "$idf_source/tools/requirements/requirements.core.txt" --constraints /opt/recipe/espidf.constraints.v6.0.txt

echo 'BUILD: mpy-cross and ESP32-S3 application only'
make -C /opt/circuitpython/mpy-cross -j4 PYTHON=/opt/idf-venv/bin/python
mkdir -p /opt/bounded-tools
cat > /opt/bounded-tools/ninja <<'SH'
#!/bin/sh
exec /opt/host-venv/bin/ninja -j4 "$@"
SH
cat > /opt/bounded-tools/cmake <<'SH'
#!/bin/sh
exec /opt/host-venv/bin/cmake "$@"
SH
chmod 700 /opt/bounded-tools/ninja /opt/bounded-tools/cmake
# IDF's exporter checks the age of this snapshot. Refresh the same reviewed
# bytes so it cannot substitute a changing upstream constraint file later.
cp /opt/recipe/espidf.constraints.v6.0.txt /opt/idf-tools/espidf.constraints.v6.0.txt
. "$idf_source/export.sh"
export PATH="/opt/bounded-tools:$PATH"
cd /opt/circuitpython/ports/espressif
make -j4 BOARD=espressif_esp32s3_devkitc_1_n8r8 PYTHON=/opt/idf-venv/bin/python \
  build-espressif_esp32s3_devkitc_1_n8r8/circuitpython-firmware.bin \
  build-espressif_esp32s3_devkitc_1_n8r8/esp-idf/partition_table/partition-table.bin

echo 'CHECK: offline image and record immutable build provenance'
python /opt/recipe/record-build.py
python /opt/recipe/verify_host_tools.py --image /output/circuitpython-firmware.bin > /output/host-tools-with-image.json
echo 'PASS: host build completed; nothing installed or deployed'
