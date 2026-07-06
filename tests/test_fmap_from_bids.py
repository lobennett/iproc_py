"""Unit tests for the fieldmap-command decision logic in
``runscript/fmap_from_bids.py``.

These test COMMAND CONSTRUCTION only (pure argv building) and require no FSL
installation. The central guarantee is parity: any non-GE/Philips manufacturer
(Siemens/Varian, unknown, or absent) must produce upstream's exact
``fsl_prepare_fieldmap SIEMENS <phase> <mag> <out> 2.46`` command.
"""
import math

from iproc.runscript.fmap_from_bids import choose_fieldmap_cmd


PHASE = "/tmp/pha_img.nii.gz"
MAG = "/tmp/mag_brain_ero.nii.gz"
OUT = "/tmp/fieldmap.nii.gz"
TWO_PI = f"{2 * math.pi:.6f}"


def _siemens_cmd(delta_te="2.46"):
    return ["fsl_prepare_fieldmap", "SIEMENS", PHASE, MAG, OUT, delta_te]


def test_ge_uses_hz_to_rad_conversion():
    cmd = choose_fieldmap_cmd("GE", 2.46, PHASE, MAG, OUT)
    assert cmd == ["fslmaths", PHASE, "-mul", TWO_PI, "-mas", MAG, OUT]


def test_ge_medical_systems_variant_matches_ge():
    # Real GE sidecars often read "GE MEDICAL SYSTEMS".
    cmd = choose_fieldmap_cmd("GE MEDICAL SYSTEMS", 2.46, PHASE, MAG, OUT)
    assert cmd[0] == "fslmaths"
    assert cmd[2:4] == ["-mul", TWO_PI]
    assert "-mas" in cmd and cmd[-1] == OUT


def test_philips_uses_hz_to_rad_conversion():
    cmd = choose_fieldmap_cmd("PHILIPS", 2.46, PHASE, MAG, OUT)
    assert cmd == ["fslmaths", PHASE, "-mul", TWO_PI, "-mas", MAG, OUT]


def test_ge_conversion_factor_is_two_pi():
    cmd = choose_fieldmap_cmd("Philips Medical Systems", 2.46, PHASE, MAG, OUT)
    scale = float(cmd[cmd.index("-mul") + 1])
    assert abs(scale - 2 * math.pi) < 1e-5


def test_siemens_matches_upstream_command():
    cmd = choose_fieldmap_cmd("SIEMENS", 2.46, PHASE, MAG, OUT)
    assert cmd == _siemens_cmd()


def test_varian_routes_to_upstream_siemens_command():
    # Upstream hardcodes the SIEMENS label and 2.46; Varian is not special-cased.
    cmd = choose_fieldmap_cmd("VARIAN", 2.46, PHASE, MAG, OUT)
    assert cmd == _siemens_cmd()


def test_missing_manufacturer_defaults_to_siemens_2_46():
    # Parity guard: absent/None/empty manufacturer -> upstream Siemens 2.46.
    for mfr in (None, "", "   ".strip()):
        assert choose_fieldmap_cmd(mfr, 2.46, PHASE, MAG, OUT) == _siemens_cmd()


def test_unknown_manufacturer_defaults_to_siemens_2_46():
    cmd = choose_fieldmap_cmd("SOME_OTHER_VENDOR", 2.46, PHASE, MAG, OUT)
    assert cmd == _siemens_cmd()


def test_siemens_delta_te_is_stringified_hardcoded_value():
    # main() always passes delta_te=2.46; confirm the argv carries "2.46".
    cmd = choose_fieldmap_cmd("SIEMENS", 2.46, PHASE, MAG, OUT)
    assert cmd[-1] == "2.46"
