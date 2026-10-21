#!/usr/bin/python3
import os
import sys
import hashlib
import secrets
import subprocess
import syslog
import time

# ==========================================
# CONFIGURATION
# The install.sh script will automatically 
# replace the UUID placeholder below.
# ==========================================
USB_MOUNT_POINT = "/mnt/usb_auth"
USB_DEV_NODE = "/dev/disk/by-uuid/REPLACE_ME_WITH_UUID"
SYSTEM_DB_PATH = "/etc/custom-auth/keys.db"
USB_KEY_PATH = f"{USB_MOUNT_POINT}/auth.key"

def log(message, is_error=False):
    """Logs PAM execution silently to journalctl for debugging."""
    level = syslog.LOG_ERR if is_error else syslog.LOG_INFO
    syslog.syslog(level, message)

def mount_usb():
    os.makedirs(USB_MOUNT_POINT, exist_ok=True)
    # capture_output=True prevents mount errors from leaking into the sudo terminal prompt
    result = subprocess.run(["mount", USB_DEV_NODE, USB_MOUNT_POINT], capture_output=True)
    return result.returncode == 0

def unmount_usb():
    subprocess.run(["umount", USB_MOUNT_POINT], capture_output=True)

def verify_and_roll():
    if not os.path.exists(USB_KEY_PATH) or not os.path.exists(SYSTEM_DB_PATH):
        log("Authentication keys missing.", is_error=True)
        return False

    # Read current state
    with open(USB_KEY_PATH, "r") as f:
        usb_secret = f.read().strip()

    with open(SYSTEM_DB_PATH, "r") as f:
        stored_hash = f.read().strip()

    # 1. Verify Cryptographic Match
    current_hash = hashlib.sha256(usb_secret.encode()).hexdigest()
    if current_hash != stored_hash:
        log("SECURITY ALERT: PAM USB key mismatch. Fallback to password.", is_error=True)
        return False

    # 2. Generate New Rolling Key
    new_secret = secrets.token_urlsafe(64)
    new_hash = hashlib.sha256(new_secret.encode()).hexdigest()

    # 3. Atomic Write to USB
    tmp_usb = f"{USB_KEY_PATH}.tmp"
    try:
        with open(tmp_usb, "w") as f:
            f.write(new_secret)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp_usb, USB_KEY_PATH)
    except Exception as e:
        log(f"PAM execution failed writing to USB: {e}", is_error=True)
        return False

    # 4. Atomic Write to System DB
    tmp_db = f"{SYSTEM_DB_PATH}.tmp"
    try:
        with open(tmp_db, "w") as f:
            f.write(new_hash)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp_db, SYSTEM_DB_PATH)
    except Exception as e:
        log(f"PAM execution failed writing to System DB: {e}", is_error=True)
        return False

    return True

if __name__ == "__main__":
    syslog.openlog(ident="usb-pam-verify", facility=syslog.LOG_AUTH)
    
    # -------------------------------------------------------------
    # CRITICAL: Fast-fail if the USB drive is not physically plugged in.
    # If we don't do this, every normal `sudo` command will hang for
    # seconds waiting for a mount timeout.
    # -------------------------------------------------------------
    if not os.path.exists(USB_DEV_NODE):
        sys.exit(1)

    # Delay slightly to let the kernel settle the block device if at cold boot
    time.sleep(0.5)

    if mount_usb():
        try:
            success = verify_and_roll()
        finally:
            unmount_usb()
            
        if success:
            log("PAM authentication successful. Access granted.")
            sys.exit(0)  # Exit 0 tells PAM to grant access
        else:
            log("PAM verification failed.", is_error=True)
    else:
        log("Failed to mount the USB device during PAM execution.", is_error=True)

    # Exit 1 tells PAM to reject the USB and prompt for normal password
    sys.exit(1)