"""
Stand-in for the `screeninfo` package, used only by the OMR child process.

OMRChecker (commit 5cf44a5) asks `screeninfo` for the monitor size when it
is imported, and fails on any machine without a display (a server, a
remote session, a background service). The size is used only to place
preview windows, which this product never opens (`show_image_level` is 0),
so a fixed value is enough.

This file is put on the child process's PYTHONPATH by checker.py. It
replaces nothing in the vendored OMRChecker and is never imported by the
web application.
"""


class _Monitor:
    width = 1920
    height = 1080


def get_monitors():
    return [_Monitor()]
