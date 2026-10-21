#!/usr/bin/python3
import os
import sys
import hashlib
import secrets
import subprocess
import time
import syslog

# ==========================================
# CONFIGURATION
# The install.sh script will automatically 
# replace the UUID placeholder below.
# ==========================================
USB_MOUNT_POINT: str = "/mnt/usb_auth"
USB_DEV_NODE: str = "/dev/disk/by-uuid/REPLACE_ME_WITH_UUID"
SYSTEM_DB_PATH: str = "/etc/custom-auth/keys.db"
USB_KEY_PATH: str = f"{USB_MOUNT_POINT}/auth.key"

def log(message, is_error=False):
    """Logs messages to the system journal for easy debugging."""
    level = syslog.LOG_ERR if is_error else syslog.LOG_INFO
    syslog.syslog(level, message)
    if is_error:
        print(f"ERROR: {message}", file=sys.stderr)
    else:
        print(message)

def mount_usb():
    os.makedirs(USB_MOUNT_POINT, exist_ok=True)
    result = subprocess.run(["mount", USB_DEV_NODE, USB_MOUNT_POINT], capture_output=True, text=True)
    if result.returncode != 0:
        log(f"Failed to mount USB: {result.stderr}", is_error=True)
        return False
    return True

def unmount_usb():
    subprocess.run(["umount", USB_MOUNT_POINT], capture_output=True)

def unlock_screen():
    # loginctl unlock-sessions instantly drops the KDE Plasma lock screen
    log("Key verified. Unlocking KDE Plasma sessions...")
    subprocess.run(["loginctl", "unlock-sessions"], check=False)

def verify_and_roll():
    if not os.path.exists(USB_KEY_PATH):
        log("Authentication file missing from USB.", is_error=True)
        return False
        
    if not os.path.exists(SYSTEM_DB_PATH):
        log("System keys.db missing. Has the system been initialized?", is_error=True)
        return False

    # Read current state
    with open(USB_KEY_PATH, "r") as f:
        usb_secret = f.read().strip()

    with open(SYSTEM_DB_PATH, "r") as f:
        stored_hash = f.read().strip()

    # 1. Verify Cryptographic Match
    current_hash = hashlib.sha256(usb_secret.encode()).hexdigest()
    if current_hash != stored_hash:
        log("SECURITY ALERT: USB key does not match system database. Cloned or desynced drive!", is_error=True)
        return False

    # 2. Generate New Rolling Key
    new_secret = secrets.token_urlsafe(64)
    new_hash = hashlib.sha256(new_secret.encode()).hexdigest()

    # 3. Atomic Write to USB
    tmp_usb_path = f"{USB_KEY_PATH}.tmp"
    try:
        with open(tmp_usb_path, "w") as f:
            f.write(new_secret)
            f.flush()
            os.fsync(f.fileno()) # Force write to physical hardware
        os.rename(tmp_usb_path, USB_KEY_PATH)
    except Exception as e:
        log(f"Failed writing new key to USB: {e}", is_error=True)
        return False

    # 4. Atomic Write to System DB
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
    
    # Give the Linux kernel a moment to populate the block device in /dev/disk/by-uuid/
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