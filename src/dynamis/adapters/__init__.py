"""Anti-corruption layer for external providers.

Intentionally empty for RES-96. One module per provider is added in RES-97+
(Women's Soccer positioning, DFL/Sportec IDSSE, SkillCorner, White CMJ,
GymAware, SPL, TACKLE, OpenBiomechanics).

Every adapter must:

* return Apache Arrow ``RecordBatch``/``RecordBatchReader`` payloads, never a
  giant ``pandas.DataFrame``;
* import its enums, units, frames, synchronization and schemas from
  :mod:`dynamis.contracts` instead of redefining them;
* preserve raw source values and units alongside the SI canonical values.
"""

__all__: list[str] = []
