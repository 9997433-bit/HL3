"""HL3 I/O layer: container schemas, readers, writers and exporters.

The only module frozen in Round 2 is :mod:`hl3.io.hdf5_schema`, which holds the
normative group/attribute/dataset names of the ``.hl3`` HDF5 container together
with a dependency-light reference writer and reader.
"""

__all__ = ["hdf5_schema"]
