# Werewolf Viewer - Task History

## 2026-03-11

### OCR optimization: local models, no-aux, shifted range, opaque masks, add-mask UI
- **analyze_names.py**: Major refactoring
  - Moved OCR models to `processing/models/` (self-contained, no global cache dependency)
  - Uses `text_detection_model_dir` / `text_recognition_model_dir` params to load from local dir
  - Disabled aux preprocessing models (doc orientation, unwarping, textline orientation)
  - Added `_init_ocr()` with CUDA GPU fallback (PaddlePaddle has no Apple MPS support)
  - Shifted primary scan range from 1000-1300s to 1100-1400s (fixes Xk65eicHSyw, no regressions on 8 videos)
  - Added extended scan: if one side missing after primary range, extends to 1400-2000s at 30s intervals
  - Extracted `_scan_range()` helper for reuse between primary and extended scans
- **Benchmark findings** (benchmark_ocr.py):
  - No-aux is 1.18x faster than with-aux, fixes detection on Xk65eicHSyw
  - Mobile models only 1.23x faster, not worth accuracy tradeoff
  - All configs run locally — PaddleOCR has no remote API
- **Web UI changes**:
  - Name masks now opaque (dark gradient with subtle line texture, no blur/transparency)
  - Added "+ Mask" button to manually add mask regions
  - Masks have × delete button on hover
- Cleaned up unused models from `~/.paddlex/official_models/` (kept only v5 server det+rec)
- Added `processing/models/` to `.gitignore` (165MB binary files)

### Polished web UI with frontend-design plugin
- **web/src/style.css**: Complete rewrite with CSS custom properties design system
  - Replaced all hardcoded colors with `:root` variables
  - Added entrance animations (fadeIn, slideInLeft, slideInRight, scaleIn)
  - Atmospheric night overlay with radial gradients and breathing animations
  - Gradient header underline, `::selection` styling, `:focus-visible` accessibility
- **web/index.html**: Swapped Inter font for Manrope + Cinzel + Uncial Antiqua
- Pre-existing uncommitted changes (main.js, player.js) included in same commit
- Commit: `a8b2a1e`

### Created comprehensive pipeline benchmark (benchmark_full.py)
- **processing/benchmark_full.py**: Full pipeline profiling script
  - Phase 1: Night detection — sequential vs parallel (3-thread) scan
  - Phase 2: Name detection timing (PaddleOCR on representative subset)
  - Phase 3: Full pipeline projection (sequential = night+names, parallel = max(night,names))
  - Ground truth validation with ±5s tolerance
  - Formatted summary tables with speedup, throughput (Nx realtime), match status
- **Results across 8 videos**:
  - 6 GT videos (720p): 1.46x night speedup, 1.95x full pipeline, 64x RT throughput, all GT pass
  - 2 non-GT videos (1080p, high-bitrate ~3GB): 1.41x night, 1.53x pipeline, 33x RT
  - All 8 videos: parallel produces identical results to sequential
- High-bitrate 1080p videos process at ~33x RT vs ~72-91x RT for 720p

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
