# syncnet-lipsync — in-file A/V sync measurement

Vendored [SyncNet](https://github.com/joonson/syncnet_python) (Chung & Zisserman)
wrapped as a CLI to measure the **baked-in audio/video offset of a media file** —
how far the audio leads or lags the picture in the file itself.

SyncNet is a two-tower CNN that matches mouth crops against MFCC audio features
and slides audio vs. video across lags to find the min-distance offset. Output
per face track: **offset in frames** (× 40 ms at the model's fixed 25 fps), an
**AV confidence** (median dist − min dist), and the min distance.

**Resolution / limits.** SyncNet operates at 25 fps → **±1 frame ≈ 40 ms**
granularity. It is reliable for gross desync (≥ ~2–3 frames) at good confidence;
sub-frame offsets (~1 frame) sit inside its noise and should not be read as exact
millisecond values. Confidence guide: `>~5` strong, `~3–5` usable, `<~2`
unreliable (treat the offset as noise).

## Install

See [INSTALL.md](INSTALL.md): venv + `pip install -r requirements.txt`, then
`sh download_model.sh` for the weights, then a `demo_syncnet.py` sanity check.
ffmpeg must be on PATH.

## Usage — CLI wrapper

`sync_offset.py` probes one or more timestamps in a file:

```
python sync_offset.py VIDEO --at 00:02:00 --at 00:05:22 [--window 12] [--vshift 15] [--keep]
```

For each `--at` it trims a short window (stream copy), runs the face pipeline +
SyncNet, and prints one result row per timestamp **as it is computed** — streamed
and flushed, so partial results survive an interruption instead of being buffered
to the end. Without `--at` the whole file is analysed (slow on long files).

**Sign convention** (also in the CLI header): `offset_ms > 0` → audio **leads**
video; `< 0` → audio **lags**; `|offset| ≤ 40 ms` at good confidence → effectively
in sync.

## Usage — upstream pipeline (per stage)

```
python run_pipeline.py  --videofile V --reference NAME --data_dir OUT   # S3FD detect + track + crop to 224px/25fps
python run_syncnet.py   --videofile V --reference NAME --data_dir OUT   # offset estimate
python run_visualise.py --videofile V --reference NAME --data_dir OUT   # overlay render
```

## Credits / provenance

- Vendored from [`joonson/syncnet_python`](https://github.com/joonson/syncnet_python)
  at base commit `907c0b5`. License: `LICENSE.md` (MIT, © 2016–present Joon Son Chung).
- SyncNet: Chung, J.S. & Zisserman, A., *"Out of time: automated lip sync in the
  wild"*, ACCV 2016 Workshop on Multi-view Lip-reading.
- Face detector (S3FD) adapted from `github.com/cs-giung/face-detection-pytorch`.
