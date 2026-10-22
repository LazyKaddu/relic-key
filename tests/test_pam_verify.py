import sys
import os
import unittest
from unittest.mock import patch, mock_open, MagicMock
import hashlib

# Add the src directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import pam_verify

class TestPamVerify(unittest.TestCase):

    def setUp(self):
        pam_verify.USB_MOUNT_POINT = "/tmp/mock_usb_auth"
        pam_verify.USB_DEV_NODE = "/dev/disk/by-uuid/MOCK_UUID"
        pam_verify.SYSTEM_DB_PATH = "/tmp/mock_custom_auth/keys.db"
        pam_verify.USB_KEY_PATH = f"{pam_verify.USB_MOUNT_POINT}/auth.key"

    @patch('pam_verify.os.makedirs')
    @patch('pam_verify.os.path.ismount', return_value=True)
    def test_mount_usb_already_mounted(self, mock_ismount, mock_makedirs):
        """If already mounted, mount_usb should return True immediately."""
        self.assertTrue(pam_verify.mount_usb())

    @patch.dict(os.environ, {"PAM_SERVICE": "sudo"})
    @patch('pam_verify.os.makedirs')
    @patch('pam_verify.os.path.ismount', return_value=False)
    @patch('pam_verify.os.path.exists', return_value=False)
    @patch('pam_verify.time.sleep')
    @patch('pam_verify.subprocess.run')
    def test_mount_usb_sudo_fast_fail(self, mock_run, mock_sleep, mock_exists, mock_ismount, mock_makedirs):
        """When running under sudo and device is missing, fast-fail without polling sleep."""
        self.assertFalse(pam_verify.mount_usb())
        mock_sleep.assert_not_called()
        mock_run.assert_not_called()

    @patch.dict(os.environ, {"PAM_SERVICE": "sddm"})
    @patch('pam_verify.os.makedirs')
    @patch('pam_verify.os.path.ismount', return_value=False)
    @patch('pam_verify.time.sleep')
    @patch('pam_verify.subprocess.run')
    @patch('pam_verify.os.path.exists')
    def test_mount_usb_settles_after_delay(self, mock_exists, mock_run, mock_sleep, mock_ismount, mock_makedirs):
        """Simulate device appearing on 3rd polling iteration during early boot."""
        # Device appears after 2 False checks
        mock_exists.side_effect = [False, False, True, True]
        mock_run.return_value = MagicMock(returncode=0)

        self.assertTrue(pam_verify.mount_usb())
        # Polling slept twice before finding device
        self.assertEqual(mock_sleep.call_count, 2)
        mock_run.assert_called_once_with(
            ["/usr/bin/mount", pam_verify.USB_DEV_NODE, pam_verify.USB_MOUNT_POINT],
            capture_output=True,
            text=True
        )

    @patch.dict(os.environ, {"PAM_SERVICE": "sddm"})
    @patch('pam_verify.os.makedirs')
    @patch('pam_verify.os.path.ismount', return_value=False)
    @patch('pam_verify.time.sleep')
    @patch('pam_verify.subprocess.run')
    @patch('pam_verify.os.path.exists', return_value=False)
    @patch('pam_verify.log')
    def test_mount_usb_timeout_missing_device(self, mock_log, mock_exists, mock_run, mock_sleep, mock_ismount, mock_makedirs):
        """Device never appears within 6 attempts; fails without attempting mount."""
        self.assertFalse(pam_verify.mount_usb())
        self.assertEqual(mock_sleep.call_count, 6)
        mock_run.assert_not_called()
        mock_log.assert_called_with(
            f"Device node missing after settling timeout: {pam_verify.USB_DEV_NODE}",
            is_error=True
        )

    @patch.dict(os.environ, {"PAM_SERVICE": "sddm"})
    @patch('pam_verify.os.makedirs')
    @patch('pam_verify.os.path.ismount', return_value=False)
    @patch('pam_verify.os.path.exists', return_value=True)
    @patch('pam_verify.time.sleep')
    @patch('pam_verify.subprocess.run')
    def test_mount_usb_retries_on_transient_mount_error(self, mock_run, mock_sleep, mock_exists, mock_ismount, mock_makedirs):
        """Mount fails on first attempt with exit code 32, succeeds on retry."""
        mock_run.side_effect = [
            MagicMock(returncode=32, stderr="Can't lookup blockdev"),
            MagicMock(returncode=0, stderr="")
        ]

        self.assertTrue(pam_verify.mount_usb())
        self.assertEqual(mock_run.call_count, 2)
        mock_sleep.assert_called_once_with(0.5)

    @patch.dict(os.environ, {"PAM_SERVICE": "sddm"})
    @patch('pam_verify.os.makedirs')
    @patch('pam_verify.os.path.ismount', return_value=False)
    @patch('pam_verify.os.path.exists', return_value=True)
    @patch('pam_verify.time.sleep')
    @patch('pam_verify.subprocess.run')
    @patch('pam_verify.log')
    def test_mount_usb_fails_all_retries(self, mock_log, mock_run, mock_sleep, mock_exists, mock_ismount, mock_makedirs):
        """Mount fails all 3 retry attempts."""
        mock_run.return_value = MagicMock(returncode=32, stderr="mount error 32")

        self.assertFalse(pam_verify.mount_usb())
        self.assertEqual(mock_run.call_count, 3)
        mock_log.assert_called_with("Mount failed after retries (code 32): mount error 32", is_error=True)

    @patch('pam_verify.os.path.exists')
    @patch('pam_verify.log')
    def test_verify_and_roll_missing_keys(self, mock_log, mock_exists):
        """Fails if USB key or system DB is missing."""
        mock_exists.side_effect = lambda p: p == pam_verify.SYSTEM_DB_PATH
        self.assertFalse(pam_verify.verify_and_roll())

        mock_exists.side_effect = lambda p: p == pam_verify.USB_KEY_PATH
        self.assertFalse(pam_verify.verify_and_roll())

    @patch('pam_verify.os.path.exists', return_value=True)
    @patch('builtins.open', new_callable=mock_open)
    @patch('pam_verify.log')
    def test_verify_and_roll_mismatch(self, mock_log, mock_file, mock_exists):
        """Fails if stored hash does not match current USB secret."""
        handlers = (
            mock_open(read_data="tampered_secret").return_value,
            mock_open(read_data="legitimate_hash").return_value
        )
        mock_file.side_effect = handlers

        self.assertFalse(pam_verify.verify_and_roll())
        mock_log.assert_called_with("SECURITY ALERT: PAM USB key mismatch. Fallback to password.", is_error=True)

    @patch('pam_verify.os.rename')
    @patch('pam_verify.os.fsync')
    @patch('pam_verify.os.path.exists', return_value=True)
    @patch('builtins.open', new_callable=mock_open)
    def test_verify_and_roll_success(self, mock_file, mock_exists, mock_fsync, mock_rename):
        """Successfully verifies secret against hash and rolls both atomically."""
        secret = "super_secure_token"
        valid_hash = hashlib.sha256(secret.encode()).hexdigest()

        handlers = (
            mock_open(read_data=secret).return_value,
            mock_open(read_data=valid_hash).return_value,
            mock_open().return_value,
            mock_open().return_value
        )
        mock_file.side_effect = handlers

        self.assertTrue(pam_verify.verify_and_roll())
        self.assertEqual(mock_fsync.call_count, 2)
        self.assertEqual(mock_rename.call_count, 2)
        mock_rename.assert_any_call(f"{pam_verify.USB_KEY_PATH}.tmp", pam_verify.USB_KEY_PATH)
        mock_rename.assert_any_call(f"{pam_verify.SYSTEM_DB_PATH}.tmp", pam_verify.SYSTEM_DB_PATH)

    @patch('pam_verify.subprocess.run')
    def test_unmount_usb(self, mock_run):
        """unmount_usb calls umount on USB_MOUNT_POINT."""
        pam_verify.unmount_usb()
        mock_run.assert_called_once_with(["/usr/bin/umount", pam_verify.USB_MOUNT_POINT], capture_output=True)

if __name__ == '__main__':
    unittest.main()
