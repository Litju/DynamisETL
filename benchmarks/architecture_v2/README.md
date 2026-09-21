# Architecture V2 benchmark harness

_Reproducible architecture-selection workloads for RES-109._

---

## 📊 Workload contract

The harness has two modes:

- `benchmark_backend.py --mode synthetic` creates deterministic CI-safe Parquet fixtures for 4k, 20k, 100k, 23-subject pose, and bounded maximum-request cases;
- `benchmark_backend.py --mode real` discovers accepted/local Parquet by modality and records only aggregate timings, row counts, compressed row-group estimates, and response sizes;
- `browser-benchmark.mjs` runs the same typed arrays through ECharts and uPlot in Chromium at 4k, 20k, and 100k points and probes initialization, first plot, heap delta, playhead, cursor/zoom, resize, bands, gaps, and synchronized updates.
- `benchmark_processors.py` profiles the existing deterministic NumPy/SciPy/PyArrow processors on synthetic fixtures and bounded accepted/local samples.

Real receipts belong under the external configured evidence cache, for example:

```powershell
$receipt = Join-Path $env:DYNAMIS_DATASET_ROOT 'cache/receipts/architecture_v2/backend.json'
& .\.venv\Scripts\python.exe benchmarks/architecture_v2/benchmark_backend.py --mode both --output $receipt
$env:RES109_BROWSER_OUTPUT = Join-Path $env:DYNAMIS_DATASET_ROOT 'cache/receipts/architecture_v2/browser.json'
node benchmarks/architecture_v2/browser-benchmark.mjs
```

CI runs only the synthetic backend mode and the contract/shape checks. Local real-data receipts are never committed.

## 🔍 Interpretation rules

The selected implementation is based on complete path cost, not library marketing or isolated microbenchmarks. `estimated_row_group_bytes` is derived from Parquet row-group statistics and compressed column sizes; it is a reproducible storage-read estimate, not an operating-system disk-counter claim.

The browser candidate must preserve exact samples, missing-data gaps, min/max display bands, playhead, range interaction, synchronized updates, deterministic axis/time conversion, and an accessible wrapper before it can replace dense Signal ECharts. ECharts remains the general analytical chart authority regardless of the dense Signal result.

## 🧪 CI self-check

The backend script is intentionally dependency-light and exits non-zero for invalid arguments, missing required time columns, failed queries, or serialization errors. A one-iteration synthetic run is the smallest executable check for the benchmark logic.
