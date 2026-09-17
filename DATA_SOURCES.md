# External data sources, licenses and notices

DynamisData ingests **external scientific datasets** that keep their own licenses
and rights. This repository contains code, configuration, contracts and
documentation only.

**Raw external datasets are never committed to Git.** Acquisition is
registry-driven from the canonical distributors listed below. CI uses synthetic
fixtures only.

The machine-readable authority is [`sources/registry.json`](sources/registry.json);
this document is its human-readable notice. Any change to one must be reflected
in the other, and a test enforces that agreement.

Project code is licensed **Apache-2.0** ([`LICENSE`](LICENSE)). That license does
**not** extend to any external dataset or to derivatives of it. NC/SA and
unclear-rights data stay outside the code license boundary.

## Registry table

| dataset_id | provider | license | redistribution | v1 role |
| --- | --- | --- | --- | --- |
| `womens-soccer-positioning` | Zenodo | CC-BY-NC-4.0 | conditional | Compact GNSS/player-positioning ingestion |
| `white-cmj-acc-grf` | Zenodo | unclear | prohibited (local-only) | Synchronized accelerometer/force validation |
| `gymaware-landmine-vision` | Zenodo | unclear | prohibited (local-only) | LPT/VBT + video agreement |
| `dfl-sportec-idsse` | Hugging Face (pysport) | CC-BY-4.0 | conditional | Elite optical tracking + synchronized events |
| `skillcorner-opendata` | SkillCorner / PySport | MIT | conditional | Broadcast tracking/events/phases + football 3D pose |
| `spl-open-data` | MLSE Sport Performance Lab | CC-BY-NC-SA-4.0 | conditional | Markerless sports 3D kinematics |
| `tackle-workload` | Zenodo | unclear | prohibited (local-only) | Optional longitudinal workload extension |
| `openbiomechanics` | Driveline Baseball R&D | CC-BY-NC-SA-4.0 (+ additional exclusion) | conditional | Optional force/mocap/high-performance validation |

## Per-source notices

### `womens-soccer-positioning`

- **Women's Soccer Positioning — 2023/2024 Spanish third category**, Zenodo record
  <https://zenodo.org/records/10913119>, DOI `10.5281/zenodo.10913119`.
- License **CC BY-NC 4.0**: non-commercial use only, attribution required.
- Do not relicense source or derived data as project code.

### `white-cmj-acc-grf`

- Zenodo record <https://zenodo.org/records/19136480>, DOI
  `10.5281/zenodo.19136480`; companion repository
  <https://github.com/markgewhite/acc2grf_prediction>.
- The upstream record currently exposes **no explicit license value**. Rights are
  not clarified, so this source is **local research input only**:
  do not redistribute or commit source or derived data pending explicit rights
  clarification.

### `gymaware-landmine-vision`

- Zenodo record <https://zenodo.org/records/18598087>, DOI
  `10.5281/zenodo.18598087`.
- No explicit license value upstream; **local research input only**, no
  redistribution of source or derived data.

### `dfl-sportec-idsse`

- Hugging Face dataset <https://huggingface.co/datasets/pysport/idsse-data>;
  dataset DOI `10.6084/m9.figshare.28196177`; method paper
  <https://doi.org/10.1038/s41597-025-04505-y>.
- License **CC BY 4.0**: attribution required; commercial reuse permitted by the
  license. V1 starts with one complete match.

### `skillcorner-opendata`

- <https://github.com/SkillCorner/opendata> and
  <https://huggingface.co/datasets/SkillCorner/opendata-bodypose>.
- License **MIT**, matching the repository and dataset card. Keep attribution and
  notices. SkillCorner requests that SkillCorner be credited when the data is used.

### `spl-open-data`

- <https://github.com/Sport-Performance-Lab/SPL-Open-Data>.
- License **CC BY-NC-SA 4.0**: non-commercial use only, attribution required, and
  **share-alike applies to data derivatives**.
- Note: this source is governed **only** by CC BY-NC-SA 4.0. The OpenBiomechanics
  professional-sports-organization / financial-analysis exclusion does **not**
  apply here and must not be attached to SPL Open Data.

### `tackle-workload`

- Zenodo record <https://zenodo.org/records/16962280>, DOI
  `10.5281/zenodo.16962280`.
- No explicit license value upstream; V1.1 optional and **local-only** unless
  rights are clarified.

### `openbiomechanics`

- <https://github.com/drivelineresearch/openbiomechanics>; see also
  <https://openbiomechanics.org>.
- Data and biomechanics documentation: **CC BY-NC-SA 4.0**. Repository code is
  separately **MIT**.
- **Additional exclusion (preserved):** any employee, contractor, or significant
  shareholder of a professional sports organization or financial analysis firm is
  forbidden any use without a specific written commercial (paid) license.
- Never treat this source as generally permissive. The adapter remains
  **optional and license-gated**.

## Excluded from V1

**SoccerMon is NOT a V1 dependency.** Its ~99 GB corpus is reserved as a future
scale/stress benchmark, after correctness and modality coverage are proven.

## Redistribution rule

- Project code may be public; raw external datasets are never committed to Git.
- Dataset acquisition is registry-driven and fetched from original/canonical
  distributors (`uv run dynamis-fetch …`), verified against the upstream size and
  checksum, and promoted atomically into immutable Bronze under
  `DYNAMIS_DATASET_ROOT`.
- CI uses synthetic fixtures, and tiny extracts only from sources whose licenses
  permit that redistribution with the required notices.
- NC/SA or unclear-license data stay outside the code license boundary.
- Every source entry stores URL/DOI, source version, checksum, retrieval time,
  citation, license identifier/status, and redistribution policy.

## Accepted RES-97 slices

The first real-data slices are `womens-soccer-positioning` **J01.xlsx** (one
matchday) and `dfl-sportec-idsse` match **J03WPY** (pinned revision
`a715a38dfbaf5f58e431727c2b78d174101a703c`: matchinformation + events +
positions). Local retrieval state (timestamps, locally computed SHA-256) belongs
to the external Bronze manifests under `DYNAMIS_DATASET_ROOT`, never to this
repository; the committed registry carries only upstream expectations and rights.

```bash
uv run dynamis-fetch  womens-soccer-positioning --version 1.0 --key J01.xlsx
uv run dynamis-ingest womens-soccer-positioning --version 1.0 --key J01.xlsx
uv run dynamis-fetch  dfl-sportec-idsse \
  --version a715a38dfbaf5f58e431727c2b78d174101a703c --match J03WPY
uv run dynamis-ingest dfl-sportec-idsse \
  --version a715a38dfbaf5f58e431727c2b78d174101a703c --match J03WPY
```

The Women's source is **CC BY-NC 4.0**: non-commercial use only, attribution
required, and neither the source nor any derived canonical output may be
committed to this repository. The DFL/Sportec source is **CC BY 4.0**:
attribution required, commercial reuse permitted by the license.

Attribution:

- Oliveira Rodriguez, L. A. (2024). *Women's team soccer positioning data,
  collected during 2023/2024 season. Third category of female soccer, Spain.*
  Zenodo. <https://doi.org/10.5281/zenodo.10913119>
- Bassek, M., et al. (2025). *An integrated dataset of synchronized
  spatiotemporal and event data in elite soccer.* Scientific Data, 12(1), 195.
  <https://doi.org/10.1038/s41597-025-04505-y> — data © Deutsche Fußball Liga
  (DFL), distributed via <https://huggingface.co/datasets/pysport/idsse-data>.
