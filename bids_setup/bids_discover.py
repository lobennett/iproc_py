#!/usr/bin/env python3
"""Thin shim: the BIDS discover logic now lives in the installed package at
``iproc.bids_app.discover`` so it is importable and wheel-packaged. This
wrapper keeps the documented ``uv run bids_setup/bids_discover.py ...`` /
``python bids_setup/bids_discover.py ...`` usage working unchanged.
"""
from iproc.bids_app.discover import main

if __name__ == "__main__":
    main()
