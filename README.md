# Fedora USB Unlocker: Rolling-Key Hardware Authentication

A secure, hardware-backed physical unlock key for Fedora KDE Linux. This project turns any standard "dumb" USB pendrive into a cryptographic token that unlocks your cold-boot SDDM login, KDE Plasma lock screen, and terminal sudo prompts automatically.

Unlike static password files that can be easily cloned, this system uses a **Rolling-Key (Write-Back OTP)** Architecture combined with atomic filesystem writes to ensure that if your USB drive is ever copied, the cloned drive will be invalidated the next time the legitimate drive is used.

---

## Features

- **Rolling-Key Cryptography**: The cryptographic secret changes every single time the drive is used, rendering cloned drives useless.
- **Zero-Touch Unlock**: Instantly dismisses the KDE lock screen upon USB insertion via udev and loginctl.
- **Cold-Boot & Sudo Integration**: Integrates directly into the Linux PAM (Pluggable Authentication Modules) stack to bypass passwords at the SDDM login screen and terminal sudo prompts.
- **SELinux Compliant**: Specifically engineered to work with Fedora's strict SELinux policies via automated context restoration.
- **Failsafe Atomic Writes**: Prevents permanent lockouts if the USB is yanked out exactly while the daemon is writing a new key.

---

## How the Rolling Key Works

To prevent "replay" or "cloning" attacks on a standard flash drive, the cryptographic processing is offloaded to the host PC:

1. **The State**: Your PC stores a hashed version of the current secret in a protected root folder (`/etc/custom-auth/keys.db`). The USB stores the plaintext secret.
2. **The Verification**: When plugged in, the system hashes the USB's plaintext secret and compares it to the local database.
3. **The Roll**: If it matches, access is granted. The system immediately generates a new cryptographically secure 64-byte string, overwrites the USB, and updates the PC's hash database.
4. **The Security**: If an attacker copies your USB, the moment either of you uses the drive, the key rolls. The out-of-sync drive will fail, immediately alerting you of the compromise while defaulting safely to your standard keyboard password.

---

## Repository Structure

```text
fedora-usb-unlock/
├── LICENSE                     # MIT License
├── README.md                   # This documentation
├── install.sh                  # Automated deployment & USB formatting utility
├── uninstall.sh                # Safely removes PAM configs, udev rules, and scripts
├── src/
│   ├── pam_verify.py           # PAM module for SDDM and sudo authentication
│   ├── auth_daemon.py          # Background service for KDE lock screen integration
│   └── udev_trigger.sh         # Hardware detection bridge
└── templates/
    └── 99-usb-unlock.rules     # Udev template populated during installation
```

---

## Prerequisites

- Fedora Linux (Tested on KDE Plasma)
- Python 3
- `parted`, `udev`, and `loginctl` (Standard on Fedora)
- A dedicated USB Flash Drive (Any capacity)

---

## Installation

> [!WARNING]
> The setup process requires a dedicated USB drive. The installation script will permanently erase all data on the selected drive to create the secure hidden partition.

1. **Clone this repository**:
   ```bash
   git clone https://github.com/LazyKaddu/relic-key.git
   cd relic-key
   ```

2. **Plug in your target USB drive.**

3. **Run the automated installer**:
   ```bash
   sudo ./install.sh
   ```

Follow the on-screen prompts to select your USB drive. The script will handle partitioning, key generation, udev rule binding, SELinux contexts, and PAM injection.

---

## Usage

- **KDE Lock Screen**: If your PC is locked, simply plug in the USB drive. udev will detect the hardware, trigger the background verification, and drop the lock screen instantly.
- **Terminal Sudo**: With the USB plugged in, type `sudo <command>`. It will execute immediately without prompting for a password. If the USB is not present, it will ask for your password as normal.
- **Cold Boot (SDDM)**: Turn on your PC and plug in the USB drive. Click your user profile, leave the password field blank, and press Enter. The PAM script will mount the drive, verify the key, and log you in.

---

## Threat Model & Fallback

- **Lost Drive**: If you lose the drive, simply type your normal user password. This system works alongside your standard password, it does not replace it. Once logged in, run `sudo ./uninstall.sh` to revoke the lost drive's access.
- **Corrupt File Write**: The system uses `os.fsync()` and temporary files to ensure atomic writes. If power is lost or the drive is pulled during a write cycle, the old key remains intact.
