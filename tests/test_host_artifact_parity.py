from __future__ import annotations

import importlib
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "firmware" / "circuitpython"
PACKAGE_PREFIXES = ("bm83", "nextion", "utils")


@contextmanager
def _import_from(base_dir: Path):
    base = str(base_dir)
    old_path = list(sys.path)
    removed = {name: sys.modules.pop(name) for name in list(sys.modules) if name.split(".")[0] in PACKAGE_PREFIXES}
    sys.path.insert(0, base)
    try:
        utils = importlib.import_module("utils")
        bm83 = importlib.import_module("bm83")
        nextion = importlib.import_module("nextion")
        yield utils, bm83, nextion
    finally:
        for name in list(sys.modules):
            if name.split(".")[0] in PACKAGE_PREFIXES:
                sys.modules.pop(name)
        sys.modules.update(removed)
        sys.path[:] = old_path


def test_core_behavior_parity_source_vs_host_artifact(tmp_path):
    """Parity check for host-simulatable behavior across source and build-style artifact trees."""
    artifact_root = tmp_path / "circuitpython"
    shutil.copytree(SRC_ROOT, artifact_root, dirs_exist_ok=True)

    with _import_from(SRC_ROOT) as (src_utils, src_bm83, src_nextion):
        with _import_from(artifact_root) as (art_utils, art_bm83, art_nextion):
            candidates = [
                None,
                "Simple text",
                "Line1\nLine2",
                'Quote "replacement"',
                "\x01\x02trim me\x03",
                "A" * 140,
            ]
            for value in candidates:
                assert src_utils.sanitize_text(value) == art_utils.sanitize_text(value)
                assert src_utils._sanitize_text(value) == art_utils._sanitize_text(value)

            src_bm = src_bm83.Bm83()
            art_bm = art_bm83.Bm83()
            payload = b"\x04"
            frame_src = src_bm.frame(src_bm83.Bm83.EVT_EQ_MODE_IND, payload)
            frame_art = art_bm.frame(art_bm83.Bm83.EVT_EQ_MODE_IND, payload)
            assert frame_src == frame_art

            fragments = [frame_src[:2], frame_src[2:4], frame_src[4:]]
            src_events = []
            art_events = []
            for fragment in fragments:
                src_bm._rx.extend(fragment)
                art_bm._rx.extend(fragment)
                src_events.extend(src_bm.poll())
                art_events.extend(art_bm.poll())
            assert src_events == art_events == [(src_bm83.Bm83.EVT_EQ_MODE_IND, payload)]

            stream = (
                b"\x1A BT_PLAY \xFF\xFF\xFF"
                b"junk\xFF\xFF\xFF"
                b"BT_NEXT\xFF\xFF\xFF"
                b"\x00EQ_ROCK\x00\xFF\xFF\xFF"
            )
            src_tokens = []
            art_tokens = []
            src_nx = src_nextion.Nextion()
            art_nx = art_nextion.Nextion()
            src_nx.process_bytes(stream, src_tokens.append)
            art_nx.process_bytes(stream, art_tokens.append)
            assert src_tokens == art_tokens == [b"BT_PLAY", b"BT_NEXT", b"EQ_ROCK"]
