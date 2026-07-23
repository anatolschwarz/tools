#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
salvage_crops.py -- recover offsets from a crashed sync_offset.py run by
re-running ONLY SyncNet's evaluate on the surviving face crops (no ffmpeg,
no S3FD). Probes with no crop are reported pending. Case SUP-52486.

Offset math is identical to sync_offset.py (imports the same helpers).

Usage:
  ~/.venvs/sup-52486-syncnet/bin/python salvage_crops.py \
      --work /tmp/syncoff_XXXX --video VIDEO --at 1:26 --at 3:36 ...
"""

import argparse
import glob
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from sync_offset import MS_PER_FRAME, MODEL, parse_ts, fmt_ts, eval_tracks, verdict  # noqa: E402


def crop_ready(work, ref):
    crops = glob.glob(os.path.join(work, "pycrop", ref, "0*.avi"))
    tracks = os.path.join(work, "pywork", ref, "tracks.pckl")
    return bool(crops) and os.path.isfile(tracks)


def main():
    ap = argparse.ArgumentParser(description="Salvage offsets from surviving crops")
    ap.add_argument("--work", required=True)
    ap.add_argument("--video", default="")
    ap.add_argument("--at", action="append", default=[], required=True)
    ap.add_argument("--vshift", type=int, default=15)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if not os.path.isdir(args.work):
        ap.error(f"work dir not found: {args.work}")
    out_path = args.out or os.path.join(args.work, "salvaged.json")

    import torch  # noqa: F401
    from SyncNetInstance import SyncNetInstance
    syncnet = SyncNetInstance()
    syncnet.loadParameters(args.model)
    print(f"[salvage] model loaded: {args.model}\n", flush=True)

    rows = {}
    for i, at in enumerate(args.at):
        ref = f"p{i:02d}"
        label = fmt_ts(parse_ts(at))
        if not crop_ready(args.work, ref):
            print(f"[{ref} {label}] no crop -- PENDING (run via original flow)", flush=True)
            rows[ref] = {"label": label, "at": at, "status": "pending"}
            continue

        tracks = eval_tracks(syncnet, ref, args.work, args.vshift)
        if not tracks:
            print(f"[{ref} {label}] crop present but no track", flush=True)
            rows[ref] = {"label": label, "at": at, "status": "no face track", "ntracks": 0}
            continue

        best = max(tracks, key=lambda t: t["conf"])
        off_ms = best["offset_frames"] * MS_PER_FRAME
        rows[ref] = {"label": label, "at": at, "status": "ok",
                     "offset_f": best["offset_frames"], "off_ms": off_ms,
                     "conf": best["conf"], "ntracks": len(tracks)}
        print(f"[{ref} {label}] offset={best['offset_frames']:+d}f "
              f"({off_ms:+.0f} ms) conf={best['conf']:.2f} tracks={len(tracks)}", flush=True)

    with open(out_path, "w") as f:
        json.dump(rows, f, indent=2)

    print(f"\nfile: {args.video}")
    print(f"salvaged rows: {out_path}")
    print(f"{'at':<14}{'offset_f':>9}{'offset_ms':>11}{'conf':>8}{'tracks':>8}   verdict")
    print("-" * 74)
    for i, at in enumerate(args.at):
        r = rows[f"p{i:02d}"]
        if r["status"] != "ok":
            print(f"{r['label']:<14}{'--':>9}{'--':>11}{'--':>8}"
                  f"{r.get('ntracks','--'):>8}   {r['status']}")
            continue
        print(f"{r['label']:<14}{r['offset_f']:>+9d}{r['off_ms']:>+10.0f}m"
              f"{r['conf']:>8.2f}{r['ntracks']:>8}   {verdict(r['off_ms'], r['conf'])}")
    print()


if __name__ == "__main__":
    main()
