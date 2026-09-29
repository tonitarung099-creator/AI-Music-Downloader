from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "ACCEPTANCE_WINDOWS_11.ps1"
LAUNCHER = ROOT / "UJI_WINDOWS_11.bat"
BUILD = ROOT / "build_portable.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "build-windows.yml"


def test_acceptance_harness_checks_physical_windows_non_admin_and_runtime():
    text = ACCEPTANCE.read_text(encoding="utf-8")
    required = [
        "Windows 11 fisik",
        "User non-admin",
        "VERSION_MANIFEST.json",
        "tools\\ffmpeg.exe",
        "tools\\ffprobe.exe",
        "tools\\deno.exe",
        "--self-test",
        "physical-acceptance-sentinel.txt",
        "acceptance-windows11.json",
        "manual_checks",
        "release_ready",
    ]
    for token in required:
        assert token in text


def test_one_click_launcher_runs_acceptance_without_admin_elevation():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "ACCEPTANCE_WINDOWS_11.ps1" in text
    assert "ExecutionPolicy Bypass" in text
    assert "Run as administrator" in text
    assert "acceptance-windows11.json" in text


def test_portable_build_bundles_acceptance_harness_and_manifest_tracks_it():
    text = BUILD.read_text(encoding="utf-8")
    assert 'Copy-Item $AcceptanceScriptPath' in text
    assert 'Copy-Item $AcceptanceLauncherPath' in text
    assert '"ACCEPTANCE_WINDOWS_11.ps1"' in text
    assert '"UJI_WINDOWS_11.bat"' in text
    assert "Uji acceptance Windows 11 fisik" in text


def test_windows_workflow_executes_harness_from_extracted_zip():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Run packaged Windows acceptance harness in CI mode" in text
    assert "Expand-Archive" in text
    assert "ACCEPTANCE_WINDOWS_11.ps1" in text
    assert "-CiMode" in text
    assert "automated_passed" in text
    assert "PACKAGED_WINDOWS_ACCEPTANCE_HARNESS_OK" in text
