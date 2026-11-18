"""Property Helper: a local-first helper for your own apartment or house hunt."""

__version__ = "0.2.0"

import re as _re

# The listing reader uses a few thousand distinct regular expressions. Python keeps only
# the last 512 compiled, so each paste recompiled most of them and reading one listing
# took about a fifth of a second. A bigger cache keeps them compiled after the first use.
if getattr(_re, "_MAXCACHE", 0) < 8192:
    _re._MAXCACHE = 8192
