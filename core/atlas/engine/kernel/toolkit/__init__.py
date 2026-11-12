"""Small dependency-free helpers the kernel owns outright.

These used to live under ``atlas.engine``, which the kernel only reached
into for four symbols. Keeping them here means the kernel's own turn path no
longer imports the legacy tree at all.
"""
