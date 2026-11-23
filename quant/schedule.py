"""Windows 작업 스케줄러에 평일 자동 실행을 등록."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

TASK = "QuantPaperTrading"
ROOT = Path(__file__).resolve().parent.parent


def _powershell(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True)


def _require_windows() -> bool:
    if sys.platform != "win32":
        print("자동 실행 등록은 Windows 전용입니다. 다른 OS에서는 cron 등에 'python -m quant paper --no-open'을 등록하세요.")
        return False
    return True


def install(at: str = "15:50") -> None:
    if not _require_windows():
        return
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", at):
        print("시각은 15:50 같은 형식으로 입력하세요.")
        return
    log_dir = ROOT / "out" / "paper"
    log_dir.mkdir(parents=True, exist_ok=True)
    bat = ROOT / "run_paper.bat"
    bat.write_text(
        "@echo off\r\n"
        "chcp 65001 > nul\r\n"
        "set PYTHONUTF8=1\r\n"
        f'cd /d "{ROOT}"\r\n'
        f'"{sys.executable}" -m quant paper --no-open > "{log_dir / "last_run.log"}" 2>&1\r\n',
        encoding="utf-8")
    q = lambda p: "'" + str(p).replace("'", "''") + "'"
    # StartWhenAvailable: 그 시각에 PC가 꺼져 있었으면 다음에 켰을 때 실행
    script = (
        f"$a = New-ScheduledTaskAction -Execute {q(bat)} -WorkingDirectory {q(ROOT)}; "
        f"$t = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At {q(at)}; "
        "$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries; "
        f"Register-ScheduledTask -TaskName {q(TASK)} -Action $a -Trigger $t -Settings $s -Force | Out-Null")
    r = _powershell(script)
    if r.returncode != 0:
        print("자동 실행 등록에 실패했습니다:\n" + (r.stderr or r.stdout).strip())
        return
    print(f"자동 실행을 등록했습니다: 평일 {at}에 모의매매를 실행하고 바탕화면 리포트를 갱신합니다.")
    print("그 시각에 PC가 꺼져 있었으면 다음에 켰을 때 실행됩니다.")
    print(f"실행 기록: {log_dir / 'last_run.log'}")
    print("해제하려면: python -m quant schedule --remove")


def remove() -> None:
    if not _require_windows():
        return
    r = _powershell(f"Unregister-ScheduledTask -TaskName '{TASK}' -Confirm:$false")
    print("자동 실행을 해제했습니다." if r.returncode == 0 else "해제 실패:\n" + (r.stderr or r.stdout).strip())
