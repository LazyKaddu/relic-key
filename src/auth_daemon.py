import os
import sys
import hashlib
import secrets
import subprocess
import time
import syslog

USB_MOUNT_POINT = "/mnt/usb_auth"
USB_DEV_NODE = "/dev/disk/by-uuid/REPLACE_ME_WITH_UUID"
SYSTEM_DB_PATH = "/etc/custom-auth/keys.db"
USB_KEY_PATH = f"{USB_MOUNT_POINT}/auth.key"

def log(message, is_error=False):
    level = syslog.LOG_ERR if is_error else syslog.LOG_INFO
    syslog.syslog(level, message)
    if is_error:
        print(f"ERROR: {message}", file=sys.stderr)
    else:
        print(message)

def mount_usb():
    os.makedirs(USB_MOUNT_POINT, exist_ok=True)
    if os.path.ismount(USB_MOUNT_POINT):
        return True
        
    # Wait up to 3 seconds for the udev UUID symlink to appear
    for _ in range(6):
        if os.path.exists(USB_DEV_NODE):
            break
        time.sleep(0.5)
        
    # Retry mount up to 3 times in case the filesystem is settling
    for attempt in range(3):
        result = subprocess.run(
            ["/usr/bin/mount", USB_DEV_NODE, USB_MOUNT_POINT],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return True
        time.sleep(0.5)
        
    log(f"Failed to mount USB after retries (code {result.returncode}): {result.stderr.strip()}", is_error=True)
    return False

def unmount_usb():
    subprocess.run(["/usr/bin/umount", USB_MOUNT_POINT], capture_output=True)

def unlock_screen():
    log("Key verified. Unlocking KDE Plasma sessions...")
    subprocess.run(["/usr/bin/loginctl", "unlock-sessions"], check=False)

def verify_and_roll():
    if not os.path.exists(USB_KEY_PATH):
        log("Authentication file missing from USB.", is_error=True)
        return False
        
    if not os.path.exists(SYSTEM_DB_PATH):
        log("System keys.db missing. Has the system been initialized?", is_error=True)
        return False

    with open(USB_KEY_PATH, "r") as f:
        usb_secret = f.read().strip()

    with open(SYSTEM_DB_PATH, "r") as f:
        stored_hash = f.read().strip()

    current_hash = hashlib.sha256(usb_secret.encode()).hexdigest()
    if current_hash != stored_hash:
        log("SECURITY ALERT: USB key does not match system database. Cloned or desynced drive!", is_error=True)
        return False

    new_secret = secrets.token_urlsafe(64)
    new_hash = hashlib.sha256(new_secret.encode()).hexdigest()

    tmp_usb_path = f"{USB_KEY_PATH}.tmp"
    try:
        with open(tmp_usb_path, "w") as f:
            f.write(new_secret)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp_usb_path, USB_KEY_PATH)
    except Exception as e:
        log(f"Failed writing new key to USB: {e}", is_error=True)
        return False

    tmp_db_path = f"{SYSTEM_DB_PATH}.tmp"
    try:
        with open(tmp_db_path, "w") as f:
            f.write(new_hash)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp_db_path, SYSTEM_DB_PATH)
    except Exception as e:
        log(f"Failed writing new hash to system DB: {e}", is_error=True)
        return False

    log("Rolling key updated successfully.")
    return True

if __name__ == "__main__":
    syslog.openlog(ident="usb-auth-daemon", facility=syslog.LOG_AUTH)
    log("USB detected by udev. Starting authentication sequence.")
    time.sleep(1.5) 
    
    if mount_usb():
        try:
            if verify_and_roll():
                unlock_screen()
        finally:
            unmount_usb()
            log("USB unmounted and daemon exiting.")
    else:
        log("Terminating early due to mount failure.", is_error=True)