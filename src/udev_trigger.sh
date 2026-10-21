#!/bin/bash
# Description: udev hardware bridge for USB authentication

ACTION=$1

if [ "$ACTION" == "unlock" ]; then
    # Start the Python daemon in the background. 
    # --no-block tells udev to fire the command and instantly return control to the kernel.
    # --collect prevents systemd from leaving dead unit files around.
    systemd-run --no-block \
                --collect \
                --unit=usb-auth-daemon-$(date +%s) \
                /usr/bin/python3 /opt/usb-auth/auth_daemon.py
                
elif [ "$ACTION" == "lock" ]; then
    # Lock all active KDE Plasma (and other) user sessions instantly
    loginctl lock-sessions
fi