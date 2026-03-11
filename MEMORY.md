# Werewolf Viewer - Task History

## 2026-03-10

### Added parallel processing optimizations to video analysis pipeline
- **analyze_night.py**: Added `ThreadPoolExecutor`-based parallel scanning (`_scan_segment` worker function)
  - Splits video into segments, each thread opens its own `VideoCapture` and seeks to segment start
  - Boundary frames handled: each thread reads one extra frame before its segment for correct diffs
  - Default 3 threads (optimal for this workload; tested 1-8, plateaus at 3)
  - Benchmark on 6 ground truth videos: **1.46x average speedup**, all results identical to sequential
  - Revert: `--workers 1` flag
- **analyze_names.py**: Converted `sample_frames` from list-returning to lazy generator
  - Uses `try/finally` for `VideoCapture` cleanup on early exit
  - Reads only frames needed (typically 10 instead of 30)
- **analyze.py**: Added subprocess-based pipeline parallelism
  - Name detection runs as separate subprocess while night detection runs in main process
  - Communicates results via temp JSON file; graceful fallback on subprocess failure
  - Suppresses PaddleOCR stderr noise with `DEVNULL` (avoids pipe buffer blocking)
  - Sets `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True` in subprocess env
  - Revert: `--sequential` flag
- **benchmark.py**: Created benchmark script validating parallel vs sequential across all ground truth videos
- **End-to-end speedup**: 91s → 58s (**1.57x**) on 62min 720p video
- Approaches tested and rejected:
  - `multiprocessing.Pool`: higher process spawn overhead than threading, no benefit
  - `ffmpeg` subprocess piping: same decode bottleneck, no speedup
  - Hardware decode (VideoToolbox): 8x slower due to GPU→CPU transfer
  - Frame seeking per sample: slower than sequential grab/skip
  - Downscaled diff computation: marginal improvement, not worth complexity
