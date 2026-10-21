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

read -p "Enter the drive letter to format (e.g., sda, sdb): " DRIVE_LETTER
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

# 3. Extract Hardware IDs via udevadm
UDEV_PROPS=$(udevadm info --query=property --name="$TARGET_DRIVE")
VENDOR_ID=$(echo "$UDEV_PROPS" | grep "^ID_VENDOR_ID=" | cut -d'=' -f2)
PRODUCT_ID=$(echo "$UDEV_PROPS" | grep "^ID_MODEL_ID=" | cut -d'=' -f2)

if [ -z "$VENDOR_ID" ] || [ -z "$PRODUCT_ID" ]; then
    echo "ERROR: Could not retrieve Vendor/Product IDs. Is it a real USB drive?"
    exit 1
fi
echo "[*] Detected USB Hardware ID: $VENDOR_ID:$PRODUCT_ID"

# 4. Partition and Format the Drive
echo "[*] Unmounting any existing partitions on $TARGET_DRIVE..."
umount ${TARGET_DRIVE}* 2>/dev/null

echo "[*] Wiping and formatting $TARGET_DRIVE..."
parted -s "$TARGET_DRIVE" mklabel gpt
parted -s -a opt "$TARGET_DRIVE" mkpart primary ext4 1MiB 50MiB

partprobe "$TARGET_DRIVE"
udevadm settle
sleep 2

PARTITION="${TARGET_DRIVE}1"

mkfs.ext4 -F -L "USB_AUTH" "$PARTITION"
udevadm settle

UUID=$(blkid -s UUID -o value "$PARTITION")
if [ -z "$UUID" ]; then
    echo "ERROR: Failed to retrieve UUID from $PARTITION!"
    exit 1
fi
echo "[*] Created new secure partition with UUID: $UUID"

# 5. Initialize Cryptographic Keys
echo "[*] Generating initial rolling keys..."
TMP_MOUNT="/mnt/usb_auth_setup"
mkdir -p "$TMP_MOUNT"
mount "$PARTITION" "$TMP_MOUNT"

SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(64), end='')")
echo -n "$SECRET" > "$TMP_MOUNT/auth.key"

mkdir -p /etc/custom-auth
echo -n "$SECRET" | sha256sum | awk '{print $1}' | tr -d '\n' > /etc/custom-auth/keys.db

umount "$TMP_MOUNT"
rm -rf "$TMP_MOUNT"

# 6. Deploy Source Code & Inject UUIDs
echo "[*] Deploying background daemon and PAM scripts..."
mkdir -p /opt/usb-auth
cp src/pam_verify.py src/auth_daemon.py src/udev_trigger.sh /opt/usb-auth/
chmod +x /opt/usb-auth/*

sed -i "s/REPLACE_ME_WITH_UUID/$UUID/g" /opt/usb-auth/pam_verify.py
sed -i "s/REPLACE_ME_WITH_UUID/$UUID/g" /opt/usb-auth/auth_daemon.py

# 7. Configure Hardware Trigger (udev)
echo "[*] Binding udev rules to hardware IDs..."
sed "s/REPLACE_VENDOR_ID/$VENDOR_ID/g; s/REPLACE_PRODUCT_ID/$PRODUCT_ID/g" templates/99-usb-unlock.rules > /etc/udev/rules.d/99-usb-unlock.rules
udevadm control --reload-rules

# 8. Configure SELinux Policies (Fedora Specific)
echo "[*] Applying SELinux security contexts..."
if command -v semanage &> /dev/null; then
    semanage fcontext -a -t bin_t "/opt/usb-auth(/.*)?" 2>/dev/null || semanage fcontext -m -t bin_t "/opt/usb-auth(/.*)?"
    restorecon -Rv /opt/usb-auth/ > /dev/null
else
    chcon -Rt bin_t /opt/usb-auth/
fi

# 9. Modify PAM Stack (SDDM, Sudo, and KDE Lock Screen)
echo "[*] Integrating with Linux PAM stack..."
PAM_RULE="auth sufficient pam_exec.so quiet seteuid /usr/bin/python3 /opt/usb-auth/pam_verify.py"

inject_sddm_pam() {
    if [ ! -f /etc/pam.d/sddm ]; then
        cat << 'EOF' > /etc/pam.d/sddm
#%PAM-1.0
auth       sufficient   pam_exec.so quiet seteuid /usr/bin/python3 /opt/usb-auth/pam_verify.py
auth       substack     system-auth
account    substack     system-auth
password   substack     system-auth
session    substack     system-auth
session    include      postlogin
EOF
        chmod 644 /etc/pam.d/sddm
        echo "  -> Created /etc/pam.d/sddm with USB verification rule."
    else
        if ! grep -q "pam_verify.py" /etc/pam.d/sddm; then
            sed -i '/^#%PAM-1.0/a '"$PAM_RULE" /etc/pam.d/sddm
            echo "  -> Added rule to /etc/pam.d/sddm"
        fi
    fi
}

inject_pam() {
    local TARGET_FILE=$1
    if [ -f "$TARGET_FILE" ]; then
        if grep -q "pam_verify.py" "$TARGET_FILE"; then
            echo "  -> PAM rule already exists in $TARGET_FILE. Skipping."
        else
            sed -i '/^#%PAM-1.0/a '"$PAM_RULE" "$TARGET_FILE"
            echo "  -> Successfully injected into $TARGET_FILE"
        fi
    fi
}

inject_sddm_pam
inject_pam "/etc/pam.d/sudo"
if [ -f /etc/pam.d/kde ]; then
    inject_pam "/etc/pam.d/kde"
fi

echo "=========================================="
echo " INSTALLATION COMPLETE! "
echo "=========================================="
echo "Your Rolling-Key USB Auth is now active."