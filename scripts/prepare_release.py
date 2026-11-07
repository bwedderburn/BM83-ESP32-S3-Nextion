#!/usr/bin/env python3
"""Compatibility entry point for the canonical committed-source packager.

Use package_source_release.py for new commands. Both entry points accept the
same arguments, scope selection, validation and output-directory rules.
"""

from package_source_release import main


if __name__ == "__main__":
    main()
