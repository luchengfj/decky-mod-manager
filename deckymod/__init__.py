"""Decky MOD Manager backend package.

MVP: local-only, stdlib-only MOD manager for RimWorld (AppID 294100).
No third-party imports, no root assumptions, no read-only toggle, no network.

Decky Loader's frozen Python ships an incomplete ``xml`` package (no
``xml.etree``); ``_ensure_elementtree()`` below repairs that in-process.

All public callables return a JSON-safe Envelope dict; see envelope.py.
"""

__version__ = "0.1.0-mvp"


def _ensure_elementtree():
    """Make ``xml.etree`` importable inside Decky Loader's frozen Python.

    Decky Loader v3.3.1 is a PyInstaller bundle whose PYZ contains a
    *partial* ``xml`` package (``xml``, ``xml.parsers``, ``xml.sax``) but NOT
    ``xml.etree``. Because the frozen package takes precedence over the
    system stdlib, ``archive.py``/``state_mutator.py`` fail with
    ``ModuleNotFoundError: No module named 'xml.etree'`` even though
    ``/usr/lib/pythonX.Y/xml/etree/`` is present on disk.

    Fix: append the real stdlib ``xml/`` directory to the already-loaded
    partial package's ``__path__`` so ``xml.etree`` resolves to the pure
    Python stdlib implementation (``pyexpat`` is bundled; the optional
    ``_elementtree`` C accelerator is not required).

    This is a no-op on a normal interpreter, uses no hardcoded Python
    version, adds no runtime dependency and does not touch Decky's bundle.
    """
    try:
        import xml.etree.ElementTree  # noqa: F401
        return
    except ImportError:
        pass

    import os
    import sys
    import xml

    xml.__path__ = list(xml.__path__)
    version = sys.version_info
    candidates = [os.path.join(p, "xml") for p in sys.path]
    for prefix in (
        getattr(sys, "base_prefix", ""),
        getattr(sys, "prefix", ""),
        "/usr/lib",
        "/usr/local/lib",
    ):
        if prefix:
            candidates.append(
                os.path.join(prefix, "python%d.%d" % (version.major, version.minor), "xml")
            )
            candidates.append(os.path.join(prefix, "Lib", "xml"))

    for directory in candidates:
        if os.path.isfile(os.path.join(directory, "etree", "ElementTree.py")):
            if directory not in xml.__path__:
                xml.__path__.append(directory)
            return

    # Nothing found: re-raise the original ImportError with its context.
    import xml.etree.ElementTree  # noqa: F401


_ensure_elementtree()
