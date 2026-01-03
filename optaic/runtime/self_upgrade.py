from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from optaic.runtime.package_update import download_wheel_from_index
from optaic.runtime.upgrade_manager import acquire_lock, log_upgrade, set_upgrade_status


def main() -> None:
    parser = argparse.ArgumentParser(description="OptAIC self-upgrade runner.")
    parser.add_argument("--job", required=True, help="Path to upgrade job JSON.")
    parser.add_argument("--wait-pid", type=int, default=None, help="PID to wait for.")
    parser.add_argument(
        "--timeout", type=int, default=300, help="Wait timeout in seconds."
    )
    args = parser.parse_args()

    job_path = Path(args.job)
    job = json.loads(job_path.read_text(encoding="utf-8"))
    if args.wait_pid is not None:
        wait_pid = args.wait_pid
    else:
        wait_pid = job.get("server_pid")
    data_dir_raw = job.get("data_dir")
    if not data_dir_raw:
        raise RuntimeError("Upgrade job missing data_dir.")
    data_dir = Path(str(data_dir_raw))
    os.environ["OPTAIC_DATA_DIR"] = str(data_dir)
    actor_principal_id = job.get("actor_principal_id")
    current_version = job.get("current_version")

    lock_handle = None
    try:
        _update_job(job_path, job, status="waiting")
        if wait_pid and int(wait_pid) > 0:
            _wait_for_pid(int(wait_pid), timeout_seconds=args.timeout)

        lock_handle = _acquire_lock_with_retry(data_dir, timeout_seconds=args.timeout)
        set_upgrade_status(data_dir, "running")
        _update_job(job_path, job, status="installing")

        skip_install = bool(job.get("skip_install"))
        wheel_path = job.get("wheel_path")
        package = job.get("package", "optaic")
        version = job.get("version")
        index_url = job.get("index_url")
        extra_index_url = job.get("extra_index_url")
        trusted_host = job.get("trusted_host")
        if wheel_path:
            wheel_path = str(wheel_path)
        if not skip_install:
            if not wheel_path and version and index_url:
                downloads_dir = data_dir / "downloads" / package / str(version)
                wheel_path = str(
                    download_wheel_from_index(
                        index_url,
                        package,
                        str(version),
                        downloads_dir,
                    )
                )
            if wheel_path:
                _run_pip(
                    ["install", "--upgrade", wheel_path],
                    index_url=index_url,
                    extra_index_url=extra_index_url,
                    trusted_host=trusted_host,
                )
            elif version:
                _run_pip(
                    ["install", "--upgrade", f"{package}=={version}"],
                    index_url=index_url,
                    extra_index_url=extra_index_url,
                    trusted_host=trusted_host,
                )
            else:
                raise RuntimeError("Upgrade job missing wheel_path and version.")
            log_upgrade(
                data_dir,
                action="package.upgrade",
                outcome="success",
                actor_principal_id=str(actor_principal_id)
                if actor_principal_id
                else None,
                before_version=str(current_version) if current_version else None,
                after_version=str(version) if version else None,
            )
        else:
            log_upgrade(
                data_dir,
                action="upgrade.restart",
                outcome="success",
                actor_principal_id=str(actor_principal_id)
                if actor_principal_id
                else None,
                before_version=str(current_version) if current_version else None,
                after_version=str(current_version) if current_version else None,
            )

        _update_job(job_path, job, status="restarting")
        if lock_handle is not None:
            lock_handle.release()
            lock_handle = None
        server_args = job.get("server_args")
        if not server_args:
            server_args = ["server"]
        cmd = [sys.executable, "-m", "optaic.cli"] + list(server_args)
        creationflags = 0
        start_new_session = False
        if sys.platform.startswith("win"):
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            start_new_session = True
        log_path = data_dir / "logs" / "restart.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(f"{_utc_now()} restart_cmd={' '.join(cmd)}\n")
            subprocess.Popen(
                cmd,
                env=os.environ.copy(),
                creationflags=creationflags,
                start_new_session=start_new_session,
                stdout=handle,
                stderr=handle,
            )
        set_upgrade_status(data_dir, "done")
        _update_job(job_path, job, status="completed")
    except Exception as exc:
        set_upgrade_status(data_dir, "failed", error=str(exc))
        log_upgrade(
            data_dir,
            action="upgrade.failed",
            outcome="failed",
            actor_principal_id=str(actor_principal_id) if actor_principal_id else None,
            before_version=str(current_version) if current_version else None,
            after_version=str(job.get("version")) if job.get("version") else None,
            detail=str(exc),
        )
        raise
    finally:
        if lock_handle is not None:
            lock_handle.release()


def _run_pip(
    args: list[str],
    *,
    index_url: str | None = None,
    extra_index_url: str | None = None,
    trusted_host: str | None = None,
) -> None:
    cmd = [sys.executable, "-m", "pip"] + args
    if index_url:
        cmd += ["--index-url", str(index_url)]
    if extra_index_url:
        cmd += ["--extra-index-url", str(extra_index_url)]
    if trusted_host:
        cmd += ["--trusted-host", str(trusted_host)]
    subprocess.run(cmd, check=True)


def _acquire_lock_with_retry(data_dir: Path, *, timeout_seconds: int) -> object:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return acquire_lock(data_dir)
        except RuntimeError as exc:
            last_error = exc
            time.sleep(0.5)
    if last_error is not None:
        raise last_error
    raise RuntimeError("Failed to acquire upgrade lock.")


def _wait_for_pid(pid: int, *, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _pid_exists(pid):
            return
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for PID {pid} to exit.")


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle == 0:
            return False
        kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    else:
        return True


def _update_job(job_path: Path, job: dict[str, object], *, status: str) -> None:
    payload = dict(job)
    payload["status"] = status
    payload["updated_at"] = _utc_now()
    job_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    main()
