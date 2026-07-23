# Install — syncnet-lipsync

Verified on Linux x86_64 (WSL2), Python 3.12, ffmpeg 6.1.

## 1. Prerequisites
- Python 3.12
- ffmpeg on PATH — check: `ffmpeg -version`

## 2. Virtualenv + dependencies
```
python3 -m venv ~/.venvs/syncnet-lipsync
~/.venvs/syncnet-lipsync/bin/pip install -r requirements.txt
```
torch/vision/audio are CPU-only wheels pulled from the PyTorch index (see the
comment at the top of `requirements.txt`). Upstream conda specs `environment.yml`
/ `environment-cpu.yml` are an alternative to pip.

## 3. Model weights
```
sh download_model.sh
```
Fetches `data/syncnet_v2.model` and `detectors/s3fd/weights/sfd_face.pth`
(≈140 MB total; not tracked in git).

## 4. Sanity check
```
~/.venvs/syncnet-lipsync/bin/python demo_syncnet.py --videofile data/example.avi --tmp_dir /tmp/syncnet
```
Expect approximately:
```
AV offset:   3
Min dist:    5.353
Confidence:  10.021
```

## 5. Run
```
~/.venvs/syncnet-lipsync/bin/python sync_offset.py VIDEO --at 00:02:00 --at 00:05:22
```
See `README.md` for the sign convention and confidence guide.
