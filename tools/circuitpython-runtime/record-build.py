#!/usr/bin/env python3
"""Record only local build artifacts and pinned provenance; never access a device."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


ROOT = Path('/opt/circuitpython')
RECIPE = Path('/opt/recipe')
OUTPUT = Path('/output')
BUILD = ROOT / 'ports/espressif/build-espressif_esp32s3_devkitc_1_n8r8'
IDF = ROOT / 'ports/espressif/esp-idf'
HASHLIB_FILES = {
    'shared-bindings/hashlib/Hash.c', 'shared-bindings/hashlib/Hash.h',
    'shared-bindings/hashlib/__init__.c', 'shared-module/hashlib/Hash.c',
    'shared-module/hashlib/Hash.h', 'shared-module/hashlib/__init__.c',
}


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_host_tools(pins):
    secure, reference = pins['security_build'], pins['reference_tools']
    if (sys.platform != 'linux' or platform.machine() not in ('x86_64', 'amd64')
            or sys.version.split()[0] != secure['python']
            or importlib.metadata.version('cryptography') != secure['cryptography']):
        raise ValueError('Unexpected isolated build host or security dependencies')
    for package, key in (('cmake', 'cmake'), ('ninja', 'ninja_python_package')):
        actual = command('/opt/host-venv/bin/python', '-c',
                         'import importlib.metadata; print(importlib.metadata.version("' + package + '"))')
        if actual != reference[key]:
            raise ValueError('Unexpected pinned host tool: ' + package)
    gcc = (Path('/opt/idf-tools/tools/xtensa-esp-elf') / reference['gcc']
           / 'xtensa-esp-elf/bin/xtensa-esp-elf-gcc')
    if reference['gcc'] not in command(str(gcc), '--version'):
        raise ValueError('Unexpected target GCC version')


def check_sources():
    pins = json.loads((RECIPE / 'source-pins.json').read_text())
    paths = {'circuitpython': ROOT, 'esp_idf': IDF,
             'esp_nimble': IDF / 'components/bt/host/nimble/nimble'}
    sources = {name: command('git', '-C', str(path), 'rev-parse', 'HEAD')
               for name, path in paths.items()}
    for name, commit in sources.items():
        if commit != pins['sources'][name]['commit']:
            raise ValueError('Unexpected pinned source: ' + name)
    board = 'ports/espressif/boards/espressif_esp32s3_devkitc_1_n8r8/sdkconfig'
    original = command('git', '-C', str(ROOT), 'show', 'HEAD:' + board)
    expected = original + '\nCONFIG_BT_NIMBLE_MAX_BONDS=8\nCONFIG_BT_NIMBLE_MAX_CCCDS=24\n'
    if (ROOT / board).read_text() != expected:
        raise ValueError('Unexpected board configuration patch')
    web_tool = 'tools/gen_web_workflow_static.py'
    original_web = command('git', '-C', str(ROOT), 'show', 'HEAD:' + web_tool) + '\n'
    if original_web.count('gzip.compress(uncompressed)') != 1:
        raise ValueError('Unexpected pinned web asset generator')
    expected_web = original_web.replace('gzip.compress(uncompressed)',
                                        'gzip.compress(uncompressed, mtime=0)')
    if (ROOT / web_tool).read_text() != expected_web:
        raise ValueError('Unexpected web asset reproducibility patch')
    runtime = pins.get('runtime_patches', {})
    if set(runtime) != {'hashlib_close'}:
        raise ValueError('Missing or unexpected reviewed native runtime patch')
    native = runtime['hashlib_close']
    if (set(native) != {'sha256', 'files'} or set(native['files']) != HASHLIB_FILES
            or sha(RECIPE / 'hashlib-close.patch') != native['sha256']):
        raise ValueError('Unexpected native hash lifetime patch provenance')
    for filename, expected_hash in native['files'].items():
        if sha(ROOT / filename) != expected_hash:
            raise ValueError('Unexpected native hash lifetime source: ' + filename)
    dirty = command('git', '-C', str(ROOT), 'diff', 'HEAD', '--name-only', '--ignore-submodules=none')
    if set(dirty.splitlines()) != {board, web_tool} | HASHLIB_FILES:
        raise ValueError('Unexpected modified source beyond the reviewed build patches')
    if command('git', '-C', str(ROOT), 'ls-files', '--others', '--exclude-standard'):
        raise ValueError('Unexpected untracked source')
    if sha(IDF / 'tools/tools.json') != pins['reference_tools']['idf_tools_json_sha256']:
        raise ValueError('Unexpected IDF tools manifest')
    secure = pins['security_build']
    if (sha(RECIPE / 'espidf.constraints.v6.0.txt') != secure['constraints_sha256']
            or sha(RECIPE / 'requirements-build.txt') != secure['requirements_sha256']):
        raise ValueError('Unexpected isolated security-build dependencies')
    check_host_tools(pins)
    return sources


def provenance_files():
    # Validate all recursive gitlinks, not a current submodule branch tip.
    submodules = command('git', '-C', str(ROOT), 'submodule', 'status', '--recursive')
    if any(line.startswith(('+', 'U')) for line in submodules.splitlines()):
        raise ValueError('A submodule differs from the recorded gitlink')
    (OUTPUT / 'submodules.txt').write_text(submodules + '\n')
    distro = command('dpkg-query', '-W', '-f=${Package}=${Version}\n')
    (OUTPUT / 'distro-manifest.txt').write_text('\n'.join(sorted(distro.splitlines())) + '\n')
    packages = []
    for name, interpreter in (('idf', '/opt/idf-venv/bin/python'),
                              ('host', '/opt/host-venv/bin/python')):
        packages.append('[' + name + ']')
        packages.extend(sorted(command(interpreter, '-m', 'pip', 'freeze', '--all').splitlines()))
    (OUTPUT / 'python-packages.txt').write_text('\n'.join(packages) + '\n')


def copy_artifacts():
    files = {
        'app': (BUILD / 'circuitpython-firmware.bin', 'circuitpython-firmware.bin'),
        'elf': (BUILD / 'firmware.elf', 'application.elf'),
        'sdkconfig': (BUILD / 'esp-idf/sdkconfig', 'sdkconfig'),
        'sdkconfig_h': (BUILD / 'esp-idf/config/sdkconfig.h', 'sdkconfig.h'),
        'partition_table': (BUILD / 'esp-idf/partition_table/partition-table.bin', 'partition-table.bin'),
        'bootloader': (BUILD / 'esp-idf/bootloader/bootloader.bin', 'bootloader.bin'),
        'mpy_cross': (ROOT / 'mpy-cross/build/mpy-cross', 'mpy-cross'),
    }
    for _name, (source, destination) in files.items():
        if not source.is_file():
            raise ValueError('Missing build artifact: ' + destination)
        shutil.copyfile(source, OUTPUT / destination)
    lock = ROOT / 'ports/espressif/dependencies.lock'
    if lock.is_file():
        shutil.copyfile(lock, OUTPUT / 'managed-dependencies.lock')
        files['managed_dependencies_lock'] = (lock, 'managed-dependencies.lock')
    return files


def artifact_entries(files):
    artifacts = {name: {'file': destination, 'sha256': sha(OUTPUT / destination)}
                 for name, (_source, destination) in files.items()}
    for name, filename in (('distro_manifest', 'distro-manifest.txt'),
                           ('python_packages', 'python-packages.txt'),
                           ('recursive_submodules', 'submodules.txt')):
        artifacts[name] = {'file': filename, 'sha256': sha(OUTPUT / filename)}
    return artifacts


def validate_board():
    if (OUTPUT / 'circuitpython-firmware.bin').stat().st_size > 2 * 1024 * 1024:
        raise ValueError('Application exceeds the reviewed stock OTA partition')
    config = (OUTPUT / 'sdkconfig').read_text()
    for setting in ('CONFIG_BT_NIMBLE_MAX_BONDS=8', 'CONFIG_BT_NIMBLE_MAX_CCCDS=24',
                    'CONFIG_BT_NIMBLE_NVS_PERSIST=y'):
        if setting not in config.splitlines():
            raise ValueError('Missing reviewed board setting: ' + setting)


def record():
    sources = check_sources()
    provenance_files()
    artifacts = artifact_entries(copy_artifacts())
    validate_board()
    manifest = {
        'schema_version': 1, 'sources': sources,
        'toolchain': {
            'python': sys.version.split()[0],
            'cmake': command('/opt/host-venv/bin/cmake', '--version').splitlines()[0],
            'ninja': command('/opt/host-venv/bin/ninja', '--version'),
            'gcc': command('xtensa-esp-elf-gcc', '--version').splitlines()[0],
            'cryptography': importlib.metadata.version('cryptography'),
            'builder_image': os.environ['BM83_BUILDER_IMAGE'],
        },
        'inputs': {'source_date_epoch': int(os.environ['SOURCE_DATE_EPOCH']),
                   'constraints_sha256': sha(RECIPE / 'espidf.constraints.v6.0.txt'),
                   'requirements_sha256': sha(RECIPE / 'requirements-build.txt'),
                   'patch_sha256': sha(RECIPE / 'bonds8-cccd24.patch'),
                   'web_assets_patch_sha256': sha(RECIPE / 'reproducible-web-assets.patch'),
                   'hashlib_close_patch_sha256': sha(RECIPE / 'hashlib-close.patch'),
                   'idf_tools_json_sha256': sha(IDF / 'tools/tools.json')},
        'artifacts': artifacts,
    }
    (OUTPUT / 'build-manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    # This separate manifest is for the existing validator's default, offline
    # image/partition checks only. It is not authorization to run --write.
    artifact = {
        'schema_version': 1, 'kind': 'circuitpython-app-only',
        'board': 'espressif_esp32s3_devkitc_1_n8r8', 'sources': sources,
        'configuration': {'CONFIG_BT_NIMBLE_MAX_BONDS': 8, 'CONFIG_BT_NIMBLE_MAX_CCCDS': 24},
        'flash_size': 8388608,
        'app': {**artifacts['app'], 'offset': 65536, 'partition_size': 2097152},
        'partition_table': {**artifacts['partition_table'], 'offset': 32768},
        'nvs': {'offset': 36864, 'size': 20480},
        'otadata': {'offset': 57344, 'size': 8192},
        'hardware_accepted': False,
    }
    (OUTPUT / 'artifact-manifest.json').write_text(json.dumps(artifact, indent=2, sort_keys=True) + '\n')
    print('PASS pinned source, partition size and reviewed sdkconfig; artifact manifest written')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-sources', action='store_true')
    args = parser.parse_args()
    if args.check_sources:
        check_sources()
        print('PASS pinned source and IDF toolchain manifest')
    else:
        record()
