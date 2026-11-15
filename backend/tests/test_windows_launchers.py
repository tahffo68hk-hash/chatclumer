from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

def test_windows_launchers_keep_the_project_directory_and_do_not_read_secrets():
    start = (ROOT / "scripts" / "start.ps1").read_text(encoding="utf-8")
    doctor = (ROOT / "scripts" / "doctor.ps1").read_text(encoding="utf-8")
    install = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
    launch = (ROOT / "启动 ChatCluster.bat").read_text(encoding="utf-8")
    phone = (ROOT / "手机访问.bat").read_text(encoding="utf-8")
    assert "Set-Location -LiteralPath $Root" in start
    assert "-WorkingDirectory $Root" in start
    assert "-WorkingDirectory $frontDir" in start
    assert "Set-Location -LiteralPath $Root" in install
    assert "Set-Location -LiteralPath $Root" in doctor
    assert "Get-Content" not in doctor
    assert "secrets.json" in doctor
    assert 'cd /d "%~dp0"' in launch
    assert 'cd /d "%~dp0"' in phone
    assert "set LAN=1" in phone
    assert '$frontHost = "127.0.0.1"' in start
    assert '"--host","127.0.0.1"' in start
