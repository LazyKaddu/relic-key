import os
import sys
import hashlib
import secrets
import subprocess
import syslog
import time

USB_MOUNT_POINT = "/mnt/usb_auth"
USB_DEV_NODE = "/dev/disk/by-uuid/d6bc3dde-8f7a-4790-9c77-37ff28f985e3"
SYSTEM_DB_PATH = "/etc/custom-auth/keys.db"
USB_KEY_PATH = f"{USB_MOUNT_POINT}/auth.key"

def log(message, is_error=False):
    level = syslog.LOG_ERR if is_error else syslog.LOG_INFO
    syslog.syslog(level, message)
    # Also write hard debug output to a file in case syslog is restricted at boot
    try:
        with open("/var/log/usb-debug/pam_runtime.log", "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")
    except Exception:
        pass

def mount_usb():
        
    # Retry loop for early-boot block device settling
    device_ready = False
    for _ in range(8):
        if os.path.exists(USB_DEV_NODE):
            device_ready = True
            break
        time.sleep(0.5)

    if not device_ready:
        log(f"Device node missing at startup after waiting: {USB_DEV_NODE}", is_error=True)
        sys.exit(1)
        

    os.makedirs(USB_MOUNT_POINT, exist_ok=True)
    if os.path.ismount(USB_MOUNT_POINT):
        return True

        
    for attempt in range(3):
        result = subprocess.run(
            ["/usr/bin/mount", USB_DEV_NODE, USB_MOUNT_POINT],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return True
        time.sleep(0.5)
        
    log(f"Mount failed (code {result.returncode}): {result.stderr.strip()}", is_error=True)
    return False

def unmount_usb():
    subprocess.run(["/usr/bin/umount", USB_MOUNT_POINT], capture_output=True)

def verify_and_roll():
    if not os.path.exists(USB_KEY_PATH) or not os.path.exists(SYSTEM_DB_PATH):
        log("Authentication keys missing.", is_error=True)
        return False

    with open(USB_KEY_PATH, "r") as f:
        usb_secret = f.read().strip()

    with open(SYSTEM_DB_PATH, "r") as f:
        stored_hash = f.read().strip()

    current_hash = hashlib.sha256(usb_secret.encode()).hexdigest()
    if current_hash != stored_hash:
        log("SECURITY ALERT: PAM USB key mismatch.", is_error=True)
        return False

    new_secret = secrets.token_urlsafe(64)
    new_hash = hashlib.sha256(new_secret.encode()).hexdigest()

    tmp_usb = f"{USB_KEY_PATH}.tmp"
    try:
        with open(tmp_usb, "w") as f:
            f.write(new_secret)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp_usb, USB_KEY_PATH)
    except Exception as e:
        log(f"Failed writing to USB: {e}", is_error=True)
        return False

    tmp_db = f"{SYSTEM_DB_PATH}.tmp"
    try:
        with open(tmp_db, "w") as f:
            f.write(new_hash)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp_db, SYSTEM_DB_PATH)
    except Exception as e:
        log(f"Failed writing to System DB: {e}", is_error=True)
        return False

    return True

if __name__ == "__main__":
    syslog.openlog(ident="usb-pam-verify", facility=syslog.LOG_AUTH)
    os.makedirs("/var/log/usb-debug", exist_ok=True)

    try:
        os.setresgid(0, 0, 0)
        os.setresuid(0, 0, 0)
    except Exception as e:
        log(f"UID elevation notice: {e}")

    if not os.path.exists(USB_DEV_NODE):
        log(f"Device node missing at startup: {USB_DEV_NODE}", is_error=True)
        sys.exit(1)

    if mount_usb():
        try:
            success = verify_and_roll()
        finally:
            unmount_usb()

        if success:
            log("PAM authentication successful. Access granted.")
            sys.exit(0)
        else:
            log("PAM verification failed.", is_error=True)

    sys.exit(1)