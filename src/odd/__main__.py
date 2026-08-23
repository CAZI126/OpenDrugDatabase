"""Allow ``python -m odd`` to behave like the installed ``odd`` command.

``odd`` is the ODD core: the minimal path from an official primary source to
provenance-carrying output an AI can consume, and back. The earlier batch,
enrichment, lineage, and diff commands are retained unchanged under
``odd-legacy`` (``python -m odd.cli.main``).
"""

from odd.core.cli import main

raise SystemExit(main())
