#!/bin/bash
# ==========================================
# FEDORA USB UNLOCKER - AUTOMATED UNINSTALLER
# ==========================================

# 1. Root Privilege Check
if [ "$EUID" -ne 0 ]; then
  echo "ERROR: This script must be run as root. Please run: sudo ./uninstall.sh"
  exit 1
fi

echo "=========================================="
echo "   REMOVING FEDORA ROLLING-KEY USB        "
echo "=========================================="

# 2. Revert PAM Stack Modifications
echo "[*] Removing PAM integrations from SDDM and Sudo..."
# We use '\@' as the sed delimiter to avoid conflicts with the forward slashes in the path
PAM_RULE="auth sufficient pam_exec.so quiet \/usr\/bin\/python3 \/opt\/usb-auth\/pam_verify.py"

if [ -f "/etc/pam.d/sddm" ]; then
    sed -i "/$PAM_RULE/d" /etc/pam.d/sddm
    echo "  -> Cleaned /etc/pam.d/sddm"
fi

if [ -f "/etc/pam.d/sudo" ]; then
    sed -i "/$PAM_RULE/d" /etc/pam.d/sudo
    echo "  -> Cleaned /etc/pam.d/sudo"
fi

# 3. Remove Hardware Trigger (udev)
echo "[*] Removing udev hardware rules..."
rm -f /etc/udev/rules.d/99-usb-unlock.rules
udevadm control --reload-rules

# 4. Clean Up Source Files and Cryptographic State
echo "[*] Deleting background daemon, PAM scripts, and key database..."
rm -rf /opt/usb-auth
rm -rf /etc/custom-auth

# 5. Remove SELinux Context Policies
echo "[*] Reverting SELinux security contexts..."
if command -v semanage &> /dev/null; then
    # Silently remove the custom context rule if it exists
    semanage fcontext -d -t bin_t "/opt/usb-auth(/.*)?" 2>/dev/null
fi

echo "=========================================="
echo " UNINSTALLATION COMPLETE! "
echo "=========================================="
echo "Your system has been fully restored to its default password authentication."