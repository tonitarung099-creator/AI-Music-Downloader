from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "ACCEPTANCE_WINDOWS_11.ps1"
LAUNCHER = ROOT / "UJI_WINDOWS_11.bat"
WORKFLOW = ROOT / ".github" / "workflows" / "build-windows.yml"


def test_physical_acceptance_records_manual_release_gate():
    text = ACCEPTANCE.read_text(encoding="utf-8")
    required = [
        "schema_version = 2",
        "manual_checks = $ManualChecks",
        "manual_confirmation_required",
        "release_ready = $false",
        'Add-ManualCheck "gui_normal"',
        'Add-ManualCheck "real_download"',
        'Add-ManualCheck "restart_persistence"',
        "WINDOWS11_PHYSICAL_ACCEPTANCE_FULL_OK",
        "RELEASE_READY_TRUE",
        "WINDOWS11_PHYSICAL_ACCEPTANCE_MANUAL_INCOMPLETE",
        "exit 2",
    ]
    for token in required:
        assert token in text


def test_ci_mode_can_never_promote_release():
    text = ACCEPTANCE.read_text(encoding="utf-8")
    assert "$Result.release_ready = $false" in text
    assert "RELEASE_READY_FALSE_CI_MODE" in text
    assert "CI hanya membuktikan acceptance otomatis" in text

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "CI tidak boleh menghasilkan release_ready=true" in workflow
    assert "CI_RELEASE_GATE_NOT_PROMOTED_OK" in workflow
    assert "manual_checks" in workflow


def test_one_click_launcher_explains_three_manual_gates():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "GUI tampil normal" in text
    assert "Satu download nyata berhasil" in text
    assert "Data tetap terbaca" in text
    assert "RELEASE_READY=TRUE" in text
    assert 'if "%EXITCODE%"=="2"' in text
    assert "acceptance-windows11.json" in text
