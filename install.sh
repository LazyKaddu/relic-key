#!/bin/bash
# ==========================================
# FEDORA USB UNLOCKER - AUTOMATED INSTALLER
# ==========================================

# 1. Root Privilege Check
if [ "$EUID" -ne 0 ]; then
  echo "ERROR: This script must be run as root. Please run: sudo ./install.sh"
  exit 1
fi

echo "=========================================="
echo "   FEDORA ROLLING-KEY USB SETUP           "
echo "=========================================="
echo "WARNING: This will PERMANENTLY ERASE all data on the selected USB drive."
echo ""

# 2. Identify USB Drives
echo "Available USB Drives:"
lsblk -o NAME,SIZE,VENDOR,MODEL,TRAN | grep -i "usb"
echo ""

read -p "Enter the drive letter to format (e.g., sdb, sdc): " DRIVE_LETTER
TARGET_DRIVE="/dev/$DRIVE_LETTER"

if [ ! -b "$TARGET_DRIVE" ]; then
    echo "ERROR: Device $TARGET_DRIVE not found!"
    exit 1
fi

read -p "Type 'YES' to irrevocably wipe $TARGET_DRIVE: " CONFIRM
if [ "$CONFIRM" != "YES" ]; then
    echo "Aborting installation."
    exit 1
fi

# 3. Extract Hardware IDs BEFORE wiping
# We read directly from the sysfs kernel attributes for the block device
VENDOR_ID=$(cat /sys/block/$DRIVE_LETTER/device/idVendor)
PRODUCT_ID=$(cat /sys/block/$DRIVE_LETTER/device/idProduct)

if [ -z "$VENDOR_ID" ] || [ -z "$PRODUCT_ID" ]; then
    echo "ERROR: Could not retrieve Vendor/Product IDs. Is it a real USB drive?"
    exit 1
fi
echo "Detected USB Hardware ID: $VENDOR_ID:$PRODUCT_ID"

# 4. Partition and Format the Drive
echo "[*] Wiping and formatting $TARGET_DRIVE..."
parted -s $TARGET_DRIVE mklabel gpt
parted -s -a opt $TARGET_DRIVE mkpart primary ext4 1MiB 50MiB

# Wait for kernel to recognize the new partition
sleep 2 
PARTITION="${TARGET_DRIVE}1"

mkfs.ext4 -F -L "USB_AUTH" $PARTITION
UUID=$(blkid -s UUID -o value $PARTITION)
echo "[*] Created new secure partition with UUID: $UUID"

# 5. Initialize Cryptographic Keys
echo "[*] Generating initial rolling keys..."
TMP_MOUNT="/mnt/usb_auth_setup"
mkdir -p $TMP_MOUNT
mount $PARTITION $TMP_MOUNT

# Generate a 64-byte random string via Python
SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(64))")
echo -n "$SECRET" > $TMP_MOUNT/auth.key

mkdir -p /etc/custom-auth
echo -n "$SECRET" | sha256sum | awk '{print $1}' > /etc/custom-auth/keys.db

umount $TMP_MOUNT
rm -rf $TMP_MOUNT

# 6. Deploy Source Code & Inject UUIDs
echo "[*] Deploying background daemon and PAM scripts..."
mkdir -p /opt/usb-auth
cp src/pam_verify.py src/auth_daemon.py src/udev_trigger.sh /opt/usb-auth/
chmod +x /opt/usb-auth/*

# Replace UUID placeholders dynamically
sed -i "s/REPLACE_ME_WITH_UUID/$UUID/g" /opt/usb-auth/pam_verify.py
sed -i "s/REPLACE_ME_WITH_UUID/$UUID/g" /opt/usb-auth/auth_daemon.py

# 7. Configure Hardware Trigger (udev)
echo "[*] Binding udev rules to hardware IDs..."
sed "s/REPLACE_VENDOR_ID/$VENDOR_ID/g; s/REPLACE_PRODUCT_ID/$PRODUCT_ID/g" templates/99-usb-unlock.rules > /etc/udev/rules.d/99-usb-unlock.rules
udevadm control --reload-rules

# 8. Configure SELinux Policies (Fedora Specific)
echo "[*] Applying SELinux security contexts..."
if command -v semanage &> /dev/null; then
    semanage fcontext -a -t bin_t "/opt/usb-auth(/.*)?"
    restorecon -Rv /opt/usb-auth/ > /dev/null
else
    echo "WARNING: 'semanage' not found. Using chcon. (Run 'sudo dnf install policycoreutils-python-utils' for permanent SELinux rules)."
    chcon -Rt bin_t /opt/usb-auth/
fi

# 9. Modify PAM Stack (SDDM and Sudo)
echo "[*] Integrating with Linux PAM stack..."
PAM_RULE="auth sufficient pam_exec.so quiet /usr/bin/python3 /opt/usb-auth/pam_verify.py"

# Function to safely inject PAM rule directly under the #%PAM-1.0 header
inject_pam() {
    local TARGET_FILE=$1
    if [ -f "$TARGET_FILE" ]; then
        if grep -q "pam_verify.py" "$TARGET_FILE"; then
            echo "  -> PAM rule already exists in $TARGET_FILE. Skipping."
        else
            # Insert the rule on the line immediately following #%PAM-1.0
            sed -i '/^#%PAM-1.0/a '"$PAM_RULE" "$TARGET_FILE"
            echo "  -> Successfully injected into $TARGET_FILE"
        fi
    fi
}

inject_pam "/etc/pam.d/sddm"
inject_pam "/etc/pam.d/sudo"

echo "=========================================="
echo " INSTALLATION COMPLETE! "
echo "=========================================="
echo "Your Rolling-Key USB Auth is now active."
echo "1. Lock your screen (Win+L) and insert the USB to test the KDE unlock."
echo "2. Open a new terminal and type 'sudo ls' to test the PAM integration."