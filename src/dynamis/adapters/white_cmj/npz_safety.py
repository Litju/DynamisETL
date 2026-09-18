"""Safe structural access to external NumPy ``.npz`` containers.

An ``.npz`` file is an untrusted ZIP containing ``.npy`` members. Two rules are
non-negotiable here:

* members are enumerated and their ``.npy`` headers are parsed **before** any
  value is read, so the code never guesses keys, shapes or dtypes;
* ``numpy.load(..., allow_pickle=False)`` is the only loading path for numeric
  members. When a distributed member is an ``object`` array --- which NumPy can
  only serialize through pickle --- this module does not fall back to
  ``allow_pickle=True``. Instead it decodes the member through
  :class:`RestrictedNumericUnpickler`, which permits exactly three globals
  (``numpy.ndarray``, ``numpy.dtype`` and the NumPy array ``_reconstruct``
  helper) and rejects every other global and every ``EXT`` opcode. The decoded
  object array is then required to contain only plain numeric, non-object
  ``numpy.ndarray`` elements within the declared rank and a bounded element
  count. A member that cannot meet that contract raises
  :class:`NpzSecurityError`.
"""

from __future__ import annotations

import io
import pickle
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

#: Largest element count a restricted unpickle may allocate for one array.
MAX_RESTRICTED_ARRAY_ELEMENTS = 1 << 26
#: Numeric dtype kinds the canonical pipeline accepts from a source member.
NUMERIC_KINDS = frozenset("fiu")


class NpzSecurityError(ValueError):
    """The container or a member violates the external-data safety contract."""


@dataclass(frozen=True, slots=True)
class NpzMemberHeader:
    """Structural facts of one ``.npy`` member, read without loading values."""

    name: str
    shape: tuple[int, ...]
    dtype: str
    fortran_order: bool
    object_dtype: bool
    compressed_size: int
    uncompressed_size: int
    crc32: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "shape": list(self.shape),
            "dtype": self.dtype,
            "fortran_order": self.fortran_order,
            "object_dtype": self.object_dtype,
            "compressed_size": self.compressed_size,
            "uncompressed_size": self.uncompressed_size,
            "crc32": f"{self.crc32:08x}",
        }


def member_name(member: str) -> str:
    """Canonical array name of an ``.npy`` member (``acc_signals.npy`` -> ``acc_signals``)."""
    return member[: -len(".npy")] if member.endswith(".npy") else member


def _read_member_header_stream(stream: Any, member: str) -> tuple[tuple[int, ...], bool, Any]:
    version = np.lib.format.read_magic(stream)
    if version == (1, 0):
        shape, fortran_order, dtype = np.lib.format.read_array_header_1_0(stream)
    elif version in {(2, 0), (3, 0)}:
        # NumPy format 3.0 shares the 2.0 header encoding (UTF-8 dict).
        shape, fortran_order, dtype = np.lib.format.read_array_header_2_0(stream)
    else:  # pragma: no cover - defensive against a future numpy format
        raise NpzSecurityError(f"{member!r}: unsupported .npy version {version!r}")
    return (
        tuple(int(dimension) for dimension in shape),
        bool(fortran_order),
        np.dtype(dtype),
    )


def read_member_data(archive: zipfile.ZipFile, member: str) -> tuple[NpzMemberHeader, bytes]:
    """Read one member, returning its header facts and the data payload only.

    The returned bytes exclude the ``.npy`` magic and header, so numeric members
    can be interpreted with ``np.frombuffer`` and object members can be fed to
    the restricted unpickler without reinterpretation.
    """
    try:
        info = archive.getinfo(member)
    except KeyError as exc:
        raise NpzSecurityError(f"{member!r} is not a member of the archive") from exc
    if info.is_dir():
        raise NpzSecurityError(f"{member!r} is a directory, not an array member")
    with archive.open(member) as stream:
        shape, fortran_order, dtype = _read_member_header_stream(stream, member)
        data = stream.read()
    header = NpzMemberHeader(
        name=member,
        shape=shape,
        dtype=dtype.str,
        fortran_order=fortran_order,
        object_dtype=bool(dtype.hasobject),
        compressed_size=info.compress_size,
        uncompressed_size=info.file_size,
        crc32=int(info.CRC),
    )
    return header, data


def read_member_header(archive: zipfile.ZipFile, member: str) -> NpzMemberHeader:
    """Parse the ``.npy`` magic and header of one member without reading values."""
    header, _ = read_member_data(archive, member)
    return header


def inspect_npz(path: Path | str) -> tuple[NpzMemberHeader, ...]:
    """Read every ``.npy`` member header of an ``.npz`` container, in file order."""
    with zipfile.ZipFile(Path(path)) as archive:
        return inspect_npz_archive(archive)


def inspect_npz_archive(archive: zipfile.ZipFile) -> tuple[NpzMemberHeader, ...]:
    members = [name for name in archive.namelist() if name.endswith(".npy")]
    if not members:
        raise NpzSecurityError("the container exposes no .npy members")
    return tuple(read_member_header(archive, member) for member in members)


def load_numeric_member(archive: zipfile.ZipFile, member: str) -> np.ndarray:
    """Load a non-object member with ``allow_pickle=False`` (never enables pickle)."""
    header, payload = read_member_data(archive, member)
    if header.object_dtype:
        raise NpzSecurityError(
            f"{member!r} is an object array; use load_object_member_numeric instead"
        )
    expected = int(np.prod(header.shape, dtype=np.int64)) if header.shape else 1
    if expected > MAX_RESTRICTED_ARRAY_ELEMENTS:
        raise NpzSecurityError(
            f"{member!r}: {expected} elements exceed the structural element bound"
        )
    array = np.frombuffer(payload, dtype=np.dtype(header.dtype), count=expected)
    return array.reshape(header.shape)


def _numpy_reconstruct() -> Any:
    numpy_module: Any = np
    core = getattr(numpy_module, "_core", None) or numpy_module.core
    return core.multiarray._reconstruct


_RECONSTRUCT = _numpy_reconstruct()
_ALLOWED_GLOBALS: dict[tuple[str, str], Any] = {
    ("numpy", "ndarray"): np.ndarray,
    ("numpy", "dtype"): np.dtype,
    ("numpy._core.multiarray", "_reconstruct"): _RECONSTRUCT,
    ("numpy.core.multiarray", "_reconstruct"): _RECONSTRUCT,
}


class RestrictedNumericUnpickler(pickle.Unpickler):
    """Unpickler that can only rebuild plain numeric NumPy arrays.

    ``find_class`` exposes exactly three globals (``numpy.ndarray``,
    ``numpy.dtype`` and the NumPy array ``_reconstruct`` helper), and ``EXT``
    opcodes are refused. Every decoded value is still validated by
    :func:`load_object_member_numeric` for dtype kind, rank and element count;
    an oversized allocation attempt surfaces as a :class:`NpzSecurityError`
    rather than an unhandled ``MemoryError``.
    """

    def find_class(self, module: str, name: str) -> Any:
        target = _ALLOWED_GLOBALS.get((module, name))
        if target is None:
            raise NpzSecurityError(f"forbidden pickle global {module}.{name}")
        return target

    def load_ext(self, *args: Any, **kwargs: Any) -> Any:
        raise NpzSecurityError("pickle EXT opcodes are forbidden in external data")


def _decode_objects(raw: bytes) -> list[Any]:
    stream = io.BytesIO(raw)
    objects: list[Any] = []
    while stream.tell() < len(raw):
        unpickler = RestrictedNumericUnpickler(stream)
        try:
            objects.append(unpickler.load())
        except MemoryError as exc:  # pragma: no cover - hostile allocation attempt
            raise NpzSecurityError(
                "restricted unpickling attempted an allocation larger than memory"
            ) from exc
    return objects


def load_object_member_numeric(
    archive: zipfile.ZipFile,
    member: str,
    *,
    expected_ndim: int,
    max_elements: int = MAX_RESTRICTED_ARRAY_ELEMENTS,
) -> list[np.ndarray]:
    """Decode an object member into plain numeric arrays through the restricted path.

    The declared NumPy object-array shape must be one-dimensional and its decoded
    elements must all be non-object, numeric ``numpy.ndarray`` values with the
    declared rank. Any deviation is a hard :class:`NpzSecurityError`.
    """
    header, payload = read_member_data(archive, member)
    if not header.object_dtype:
        raise NpzSecurityError(f"{member!r} is not an object array")
    if len(header.shape) != 1:
        raise NpzSecurityError(
            f"{member!r}: object members must be one-dimensional, found shape {header.shape}"
        )
    declared = header.shape[0]
    objects = _decode_objects(payload)
    if len(objects) == 1 and isinstance(objects[0], np.ndarray) and objects[0].dtype.hasobject:
        container = objects[0]
        if tuple(container.shape) != header.shape:
            raise NpzSecurityError(
                f"{member!r}: decoded object array shape {tuple(container.shape)} does not "
                f"match the declared shape {header.shape}"
            )
        if container.size > max_elements:
            raise NpzSecurityError(
                f"{member!r}: object container exceeds the element bound ({container.size})"
            )
        elements = [container[index] for index in range(declared)]
    elif len(objects) == declared:
        elements = objects
    else:
        raise NpzSecurityError(
            f"{member!r}: decoded {len(objects)} pickle payloads for {declared} declared elements"
        )
    arrays: list[np.ndarray] = []
    for index, element in enumerate(elements):
        if not isinstance(element, np.ndarray):
            raise NpzSecurityError(
                f"{member!r}[{index}] is {type(element).__name__}, not a numpy array"
            )
        if element.dtype.hasobject or element.dtype.kind not in NUMERIC_KINDS:
            raise NpzSecurityError(f"{member!r}[{index}] has forbidden dtype {element.dtype.str!r}")
        if element.ndim != expected_ndim:
            raise NpzSecurityError(
                f"{member!r}[{index}] has rank {element.ndim}, expected {expected_ndim}"
            )
        if element.size > max_elements:
            raise NpzSecurityError(f"{member!r}[{index}] exceeds the element bound")
        arrays.append(np.asarray(element))
    return arrays
