# Source catalog

`SourceCatalogEntry` records upstream metadata before bytes are acquired. Its identity is provider/dataset plus external object ID and object kind (contest, season dataset, release asset or aggregate). It retains sport/competition/edition/team facts only when declared, upstream URL and revision, asset identity and size, rights, upstream capabilities, discovery time and local availability.

The state path is `UPSTREAM_AVAILABLE → REGISTERED → ACQUIRED → MATERIALIZED → READY`. Acquisition, materialization and validation failures have distinct states and retain evidence. Transitions are deterministic and do not silently skip gates. A catalog listing must not download or materialize dense data. An upstream row is not a scientific Session. A materialized Session may link to its source entry.

Upstream capability and local/materialized capability are separate facts. Rights stay attached to the catalog record and continue through Bronze promotion. Registration mirrors source registry metadata only; acquisition still requires the existing deterministic checksum and rights gates.
