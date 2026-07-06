#!/usr/bin/env python3
"""Thin shim: the BIDS generate logic now lives in the installed package at
``iproc.bids_app.generate`` so it is importable and wheel-packaged. This
wrapper keeps the documented ``uv run bids_setup/bids_generate.py ...`` /
``python bids_setup/bids_generate.py ...`` usage working unchanged.
"""
from iproc.bids_app.generate import main

if __name__ == "__main__":
    main()
