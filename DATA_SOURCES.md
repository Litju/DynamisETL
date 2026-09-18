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
| `white-cmj-acc-grf` | Zenodo | CC-BY-4.0 | conditional | Synchronized accelerometer/force validation |
| `gymaware-landmine-vision` | Zenodo | CC-BY-4.0 | conditional | LPT/VBT + video agreement |
| `dfl-sportec-idsse` | Hugging Face (pysport) | CC-BY-4.0 | conditional | Elite optical tracking + synchronized events |
| `skillcorner-opendata` | SkillCorner / PySport | MIT | conditional | Broadcast tracking/events/phases + football 3D pose |
| `spl-open-data` | MLSE Sport Performance Lab | CC-BY-NC-SA-4.0 (+ role-dependent exclusion) | conditional | Markerless sports 3D kinematics |
| `tackle-workload` | Zenodo | unclear | prohibited (local-only) | Optional longitudinal workload extension |
| `openbiomechanics` | Driveline Baseball R&D | CC-BY-NC-SA-4.0 (+ additional exclusion) | conditional | Optional force/mocap/high-performance validation |

## Rights evidence

[`sources/rights_evidence.json`](sources/rights_evidence.json) is the
reproducible authority/provenance receipt for the RES-104 rights decisions. For
each audited dataset it records the source URL/DOI, authority type, observed
license identifier, source/revision/date, any rendered-record discrepancy and
the resulting decision; `tests/test_rights_evidence.py` keeps it in agreement
with the registry. The audit path fetches **licensing metadata only** (for
example the Zenodo record API and the rendered record page); no dataset payload
is fetched to inspect rights.

## Per-source notices

### `womens-soccer-positioning`

- **Women's Soccer Positioning — 2023/2024 Spanish third category**, Zenodo record
  <https://zenodo.org/records/10913119>, DOI `10.5281/zenodo.10913119`.
- License **CC BY-NC 4.0**: non-commercial use only, attribution required.
- Do not relicense source or derived data as project code.
- The provider publishes geographic GNSS/GPS latitude/longitude but its metadata
  does **not** explicitly declare a geodetic datum. The pipeline's canonical
  interpretation is **WGS 84**, recorded as a documented inference (never as a
  provider declaration); no datum transformation is applied and source
  coordinate values pass through unchanged.

### `white-cmj-acc-grf`

- Zenodo record <https://zenodo.org/records/19136480>, version **v1**, DOI
  `10.5281/zenodo.19136480`. The record's own `code:codeRepository` metadata links
  <https://github.com/markgewhite/acc2grf_prediction> (currently 404); the verified
  companion pipeline for the same deposit is <https://github.com/markgewhite/acc2grf-cmj>.
- Rights: **CC BY 4.0** (attribution required; redistribution conditional),
  promoted by RES-104 on reproducible evidence recorded in
  [`sources/rights_evidence.json`](sources/rights_evidence.json): the Zenodo API
  record's `metadata.license.id` is `cc-by-4.0`, the rendered record Rights/License
  display shows Creative Commons Attribution 4.0 International, and the
  author-controlled companion repository states that the preprocessed data are
  deposited separately under CC-BY-4.0 for this exact DOI. RES-98's audit reported
  a blank rendered Rights/License display; RES-104 did not reproduce that
  observation on 2026-09-18 and records the discrepancy rather than inferring from
  the PLOS article license.
- Verified v1 structure: `cmj_dataset_both.npz` holds 663 trials (67 distinct
  distributed subject ids), a full per-trial triaxial accelerometer member at
  250 Hz in `g`, and a per-trial pre-takeoff vGRF member at 1000 Hz normalized by
  body weight. The record prose describes a 500-sample 2000 ms pre-takeoff window,
  but the distributed arrays are longer; RES-98 canonicalizes the released arrays
  as distributed and never fabricates the window.
- Sensor-placement documentation conflict preserved: the 2026 distributed record
  places the lower-back sensor at **L5**, the 2022 acquisition paper at **L4**.
  No placement is chosen and no signal is altered.

### `gymaware-landmine-vision`

- Zenodo record <https://zenodo.org/records/18598087>, version **v1**, DOI
  `10.5281/zenodo.18598087`.
- Rights: **CC BY 4.0** (attribution required; redistribution conditional),
  promoted by RES-104 on the deposit's own authority recorded in
  [`sources/rights_evidence.json`](sources/rights_evidence.json): the Zenodo API
  record's `metadata.license.id` is `cc-by-4.0` and the rendered record
  Rights/License display shows Creative Commons Attribution 4.0 International.
  No author-controlled companion statement for the deposit was located. The
  related article's open-access license is **not** used as authority; RES-98's
  reported blank rendered Rights/License display was not reproduced on
  2026-09-18 and the discrepancy is recorded.
- Verified v1 structure: `LP_data.zip` contains per-set GymAware CSV exports with
  rep-level summary indicators only (no sample-level trajectory), a vision
  workbook whose numeric values are populated for one example row, YOLO training
  code and raw video. RES-98 imports source-provided trial metrics only and does
  not fabricate any dense LPT stream.
- Method metadata preserved from the study protocol: vision uses the full bar
  (≈2.20 m), the GymAware attachment/effective radius is ≈2.05 m. No cross-method
  correction is applied in RES-98.

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

- <https://github.com/Sport-Performance-Lab/SPL-Open-Data>, pinned revision
  `a3f9cffbde917b1e1747cedd6ec25dfab18c6051`.
- License **CC BY-NC-SA 4.0**: non-commercial use only, attribution required, and
  **share-alike applies to data derivatives**.
- **Additional role-dependent exclusion, present in SPL's own `LICENSE` at the
  pinned revision:** any employee or contractor employed by, associated with, or a
  significant shareholder of a professional sports organization or financial
  analysis firm is forbidden to use SPL Open Data for any use whatsoever without a
  specific written commercial (paid) license. This restriction is SPL's own; it is
  quoted here from the pinned `LICENSE` and is not copied from OpenBiomechanics.
- Acquisition **fails closed**: `dynamis-fetch spl-open-data` refuses to plan or
  fetch until the operator passes
  `--acknowledge-spl-license-restrictions`. The acknowledgement records that the
  operator has read the restriction; it does not assert legal eligibility, does
  not override the NC/SA obligations, and eligibility remains the operator's
  responsibility. The acknowledgement is source-specific so it cannot silently
  satisfy any unrelated future license.

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

## Accepted RES-98 slices

The laboratory slices are White CMJ `white-cmj-acc-grf` **v1**
(`cmj_dataset_both.npz` only; the per-condition archives duplicate the same
accepted corpus) and GymAware landmine `gymaware-landmine-vision` **v1**
(`LP_data.zip`). Both are declared **CC BY 4.0** (attribution required,
redistribution conditional) after the RES-104 rights audit; the registry keeps
source versions and upstream checksums, while retrieval timestamps and locally
computed SHA-256 live only in the external Bronze manifests. Raw source payloads
and derived canonical outputs are still **never committed to Git**.

```bash
uv run dynamis-fetch  white-cmj-acc-grf --version v1 --key cmj_dataset_both.npz
uv run dynamis-ingest white-cmj-acc-grf --version v1 --key cmj_dataset_both.npz --discovery
uv run dynamis-fetch  gymaware-landmine-vision --version v1 --key LP_data.zip
uv run dynamis-ingest gymaware-landmine-vision --version v1 --key LP_data.zip --discovery
```

Attribution:

- White, M. (2026). *Preprocessed accelerometer and ground reaction force data
  from countermovement jumps (Python format).* Zenodo.
  <https://doi.org/10.5281/zenodo.19136480>
- Zhao, R. (2026). *A landmine press test involving 24 male athletes, based on
  video-based and GymAware measurements.* Zenodo.
  <https://doi.org/10.5281/zenodo.18598087>
