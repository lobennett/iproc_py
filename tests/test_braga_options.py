from iproc.bids_app.generate import (
    build_parser, resolve_braga_options, BRAGA_DEFAULTS, FS6_HOME, FS7_HOME,
)

def _opts(*argv):
    # every parse needs the required positional + --iproc-dir
    args = build_parser().parse_args(["m.yaml", "--iproc-dir", "out", *argv])
    return resolve_braga_options(args)

def test_default_no_braga_is_upstream_defaults():
    o = _opts()
    assert o["braga_mode"] is False
    assert o["resolution"] is None          # fall back to manifest
    assert o["brain_extract"] == "bet"
    assert o["fs_version"] == 6
    assert o["freesurfer_home"] == FS6_HOME
    assert o["native_surface"] is False
    assert o["slice_timing"] is False
    assert o["nordic"] is False
    assert o["marss"] is False

def test_braga_preset_sets_full_set():
    o = _opts("--braga")
    assert o["braga_mode"] is True
    assert o["resolution"] == 111
    assert o["brain_extract"] == "synthstrip"
    assert o["fs_version"] == 7
    assert o["freesurfer_home"] == FS7_HOME
    assert o["native_surface"] is True
    # opt-in even in braga -> stay off
    assert o["slice_timing"] is False
    assert o["nordic"] is False
    assert o["marss"] is False

def test_granular_flag_overrides_preset():
    o = _opts("--braga", "--brain-extract", "bet")
    assert o["braga_mode"] is True
    assert o["brain_extract"] == "bet"      # override wins
    assert o["resolution"] == 111           # rest still braga

def test_no_native_surface_overrides_braga():
    o = _opts("--braga", "--no-native-surface")
    assert o["native_surface"] is False

def test_resolution_flag_without_braga():
    o = _opts("--resolution", "111")
    assert o["braga_mode"] is False
    assert o["resolution"] == 111

def test_explicit_freesurfer_home_wins_over_fs_version():
    o = _opts("--braga", "--freesurfer-home", "/custom/fs")
    assert o["freesurfer_home"] == "/custom/fs"

def test_optin_denoise_flags_enable_individually():
    o = _opts("--nordic", "--marss", "--mbfactor", "8", "--slice-timing")
    assert o["nordic"] is True
    assert o["marss"] is True
    assert o["mbfactor"] == 8
    assert o["slice_timing"] is True
