from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.services import runtime_self_test
from app.services.runtime_self_test import RuntimeSelfTestError, run_portable_runtime_self_test


def _make_tools(root: Path) -> None:
    tools = root / "tools"
    tools.mkdir(parents=True)
    for name in ("ffmpeg.exe", "ffprobe.exe", "deno.exe"):
        (tools / name).write_bytes(b"fixture")


def test_stage6_runtime_self_test_requires_ffprobe(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "ffmpeg.exe").write_bytes(b"fixture")
    (tools / "deno.exe").write_bytes(b"fixture")

    with pytest.raises(RuntimeSelfTestError, match="ffprobe"):
        run_portable_runtime_self_test(tmp_path)


def test_stage6_runtime_self_test_exercises_versions_and_audio(tmp_path, monkeypatch):
    _make_tools(tmp_path)
    calls: list[list[str]] = []

    def fake_runner(command, **kwargs):
        command = [str(part) for part in command]
        calls.append(command)
        executable = Path(command[0]).name.lower()

        if executable == "ffmpeg.exe" and "-version" in command:
            return subprocess.CompletedProcess(command, 0, "ffmpeg version 9.0\n", "")
        if executable == "ffprobe.exe" and "-version" in command:
            return subprocess.CompletedProcess(command, 0, "ffprobe version 9.0\n", "")
        if executable == "deno.exe" and "--version" in command:
            return subprocess.CompletedProcess(command, 0, "deno 2.9.7\n", "")
        if executable == "ffprobe.exe" and "-of" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps({"streams": [{"codec_type": "audio", "codec_name": "aac"}]}),
                "",
            )
        if executable == "ffmpeg.exe":
            Path(command[-1]).write_bytes(b"audio-fixture")
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(f"Perintah tak terduga: {command}")

    monkeypatch.setattr(runtime_self_test, "_verify_ejs_bundle", lambda: "0.8.0")
    result = run_portable_runtime_self_test(tmp_path, timeout=3, runner=fake_runner)

    assert result["audio_fixture"] == "ok"
    assert result["yt_dlp_ejs"] == "0.8.0"
    assert result["ffmpeg"].startswith("ffmpeg version")
    assert result["ffprobe"].startswith("ffprobe version")
    assert result["deno"] == "deno 2.9.7"
    assert any("sine=frequency=880:duration=0.25" in call for call in calls)
    assert any("aac" in call for call in calls)
    assert any(Path(call[0]).name.lower() == "ffprobe.exe" and "-of" in call for call in calls)


def test_stage6_runtime_self_test_turns_tool_timeout_into_release_failure(tmp_path, monkeypatch):
    _make_tools(tmp_path)
    monkeypatch.setattr(runtime_self_test, "_verify_ejs_bundle", lambda: "0.8.0")

    def timed_out(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs.get("timeout", 1))

    with pytest.raises(RuntimeSelfTestError, match="timeout"):
        run_portable_runtime_self_test(tmp_path, timeout=1, runner=timed_out)


def test_stage6_external_tool_pins_are_immutable_and_hashed():
    pins = json.loads(Path("release-tools.json").read_text(encoding="utf-8"))

    assert pins["ffmpeg"]["version"] == "9.0"
    assert "ffmpeg-9.0-essentials_build.zip" in pins["ffmpeg"]["url"]
    assert "latest" not in pins["ffmpeg"]["url"].lower()
    assert len(pins["ffmpeg"]["sha256"]) == 64

    assert pins["deno"]["version"] == "2.9.7"
    assert "/v2.9.7/" in pins["deno"]["url"]
    assert "latest" not in pins["deno"]["url"].lower()
    assert len(pins["deno"]["sha256"]) == 64


def test_stage6_direct_runtime_requirements_are_exact_pins():
    lines = [
        line.strip()
        for line in Path("requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert lines
    assert all("==" in line for line in lines)
