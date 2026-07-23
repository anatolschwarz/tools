#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_offset.py -- measure the baked-in A/V sync offset of a video FILE with SyncNet.

Case SUP-52486. Scope: the in-file audio/video offset only (see CLAUDE.md);
playback-side causes are out of scope.

For each --at timestamp we trim a short window (stream copy, preserves the
original A/V content lag), run the SyncNet face pipeline + offset estimator on
it, and report the offset of the highest-confidence face track. Without --at the
whole file is analysed (slow on long files).

SIGN CONVENTION  (verified empirically -- see README.md "Sign convention"):
  offset_ms > 0  =>  AUDIO LEADS video (sound arrives before the lips)
  offset_ms < 0  =>  AUDIO LAGS  video (sound arrives after the lips)
  |offset_ms| <= ~40 ms (1 frame) with good confidence  =>  effectively in sync.

CONFIDENCE (SyncNet AV confidence = median dist - min dist):
  >~5 strong lock, ~3-5 usable, <~2 weak/unreliable (treat offset as noise).

Usage:
  ~/.venvs/sup-52486-syncnet/bin/python sync_offset.py VIDEO \
      --at 00:10:00 --at 00:18:30 [--window 12] [--vshift 15] [--keep]
"""

import argparse
import glob
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

FPS = 25
MS_PER_FRAME = 1000.0 / FPS          # 40 ms
MODEL = os.path.join(SCRIPT_DIR, "data", "syncnet_v2.model")

logging.basicConfig(level=logging.WARNING, format="%(message)s")
log = logging.getLogger("sync_offset")


def parse_ts(s):
    """Accept SS(.ms), MM:SS, HH:MM:SS, or a bare float -> seconds."""
    s = str(s).strip()
    if ":" in s:
        parts = [float(p) for p in s.split(":")]
        sec = 0.0
        for p in parts:
            sec = sec * 60 + p
        return sec
    return float(s)


def fmt_ts(sec):
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def trim_clip(video, start, dur, out):
    """Fast keyframe-seek stream copy. Both streams are shifted together, so the
    original audio-vs-video content lag (what we measure) is preserved; any tiny
    start-of-clip timestamp skew is normalised by run_pipeline's -async 1."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-ss", f"{start:.3f}", "-i", video, "-t", f"{dur:.3f}",
           "-c", "copy", "-avoid_negative_ts", "make_zero", out]
    subprocess.run(cmd, check=True)


def run_pipeline(clip, ref, data_dir):
    cmd = [sys.executable, os.path.join(SCRIPT_DIR, "run_pipeline.py"),
           "--videofile", clip, "--reference", ref,
           "--data_dir", data_dir, "--overwrite"]
    # cwd=SCRIPT_DIR so `from detectors import S3FD` and the relative
    # PATH_WEIGHT './detectors/s3fd/weights/sfd_face.pth' resolve.
    subprocess.run(cmd, check=True, cwd=SCRIPT_DIR,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def eval_tracks(syncnet, ref, data_dir, vshift):
    """Run SyncNet on every cropped face track; return list of dicts."""
    crops = sorted(glob.glob(os.path.join(data_dir, "pycrop", ref, "0*.avi")))
    tmp_dir = os.path.join(data_dir, "pytmp_eval")
    out = []
    for c in crops:
        opt = SimpleNamespace(tmp_dir=tmp_dir, reference=ref,
                              batch_size=20, vshift=vshift)
        offset, conf, _ = syncnet.evaluate(opt, videofile=c)
        out.append({"track": os.path.basename(c),
                    "offset_frames": int(offset),
                    "conf": float(conf)})
    return out


def main():
    ap = argparse.ArgumentParser(description="Measure in-file A/V sync with SyncNet")
    ap.add_argument("video", help="input video file")
    ap.add_argument("--at", action="append", default=[],
                    help="timestamp to probe (HH:MM:SS / MM:SS / seconds); repeatable")
    ap.add_argument("--window", type=float, default=12.0,
                    help="clip length in seconds centred on each --at (default 12)")
    ap.add_argument("--vshift", type=int, default=15,
                    help="max search shift in frames (+/-); default 15 = +/-600 ms")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--keep", action="store_true", help="keep the temp work dir")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)

    if not os.path.isfile(args.video):
        ap.error(f"video not found: {args.video}")
    if not os.path.isfile(args.model):
        ap.error(f"model not found: {args.model} (run download_model.sh)")

    import torch  # noqa: F401  (import after arg validation for fast --help)
    from SyncNetInstance import SyncNetInstance

    syncnet = SyncNetInstance()
    syncnet.loadParameters(args.model)
    log.info("model loaded: %s", args.model)

    work = tempfile.mkdtemp(prefix="syncoff_")

    # Stream results: print the header up front and each probe's row the moment
    # it is computed (flushed immediately). Partial results then survive a crash
    # and can be tailed live -- they are no longer buffered until the end.
    print(f"\nfile: {args.video}")
    print(f"{'at':<14}{'offset_f':>9}{'offset_ms':>11}{'conf':>8}{'tracks':>8}   verdict")
    print("-" * 74, flush=True)

    def emit(row):
        print(format_row(row), flush=True)

    try:
        probes = args.at if args.at else [None]  # None => whole file
        for i, at in enumerate(probes):
            ref = f"p{i:02d}"
            if at is None:
                clip = args.video
                label = "whole file"
            else:
                sec = parse_ts(at)
                start = max(0.0, sec - args.window / 2.0)
                clip = os.path.join(work, f"{ref}.mp4")
                trim_clip(args.video, start, args.window, clip)
                label = fmt_ts(sec)

            try:
                run_pipeline(clip, ref, work)
                tracks = eval_tracks(syncnet, ref, work, args.vshift)
            except subprocess.CalledProcessError as e:
                emit((label, None, "pipeline error", None, 0))
                log.warning("pipeline failed at %s: %s", label, e)
                continue

            if not tracks:
                emit((label, None, "no face track", None, 0))
                continue

            best = max(tracks, key=lambda t: t["conf"])
            off_ms = best["offset_frames"] * MS_PER_FRAME
            emit((label, best["offset_frames"], off_ms,
                  best["conf"], len(tracks)))
    finally:
        if args.keep:
            log.warning("work dir kept: %s", work)
        else:
            shutil.rmtree(work, ignore_errors=True)

    print()


def format_row(row):
    """Format one result tuple as a table line."""
    label, off_f, off_ms, conf, ntr = row
    if off_f is None:  # error / no track (off_ms holds the reason string)
        return f"{label:<14}{'--':>9}{'--':>11}{'--':>8}{ntr:>8}   {off_ms}"
    return (f"{label:<14}{off_f:>+9d}{off_ms:>+10.0f}m{conf:>8.2f}{ntr:>8}"
            f"   {verdict(off_ms, conf)}")


def verdict(off_ms, conf):
    if conf < 2:
        return "weak confidence -- unreliable"
    if abs(off_ms) <= MS_PER_FRAME:
        return "in sync (<=1 frame)"
    lead = "audio leads" if off_ms > 0 else "audio lags"
    return f"{lead} by {abs(off_ms):.0f} ms"


if __name__ == "__main__":
    main()
