import sys
import os
import unittest
from unittest.mock import patch, mock_open, MagicMock
import hashlib

# Add the src directory to the path so we can import auth_daemon
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import auth_daemon

class TestAuthDaemon(unittest.TestCase):

    def setUp(self):
        # Override paths so we don't accidentally touch real system files
        auth_daemon.USB_KEY_PATH = "/tmp/mock_usb/auth.key"
        auth_daemon.SYSTEM_DB_PATH = "/tmp/mock_db/keys.db"

    @patch('auth_daemon.os.path.exists')
    @patch('auth_daemon.log')
    def test_missing_files(self, mock_log, mock_exists):
        """Test that verification fails safely if the USB or DB file is missing."""
        # Simulate USB key missing
        mock_exists.side_effect = lambda p: p == auth_daemon.SYSTEM_DB_PATH
        self.assertFalse(auth_daemon.verify_and_roll())

        # Simulate System DB missing
        mock_exists.side_effect = lambda p: p == auth_daemon.USB_KEY_PATH
        self.assertFalse(auth_daemon.verify_and_roll())

    @patch('auth_daemon.os.path.exists', return_value=True)
    @patch('builtins.open', new_callable=mock_open)
    @patch('auth_daemon.log')
    def test_cryptographic_mismatch(self, mock_log, mock_file, mock_exists):
        """Test that verification fails if the USB key hash doesn't match the system DB."""
        # Simulate reading 'wrong_secret' from USB and 'correct_hash' from DB
        handlers = (
            mock_open(read_data="wrong_secret").return_value,
            mock_open(read_data="correct_hash").return_value
        )
        mock_file.side_effect = handlers

        self.assertFalse(auth_daemon.verify_and_roll())
        mock_log.assert_called_with("SECURITY ALERT: USB key does not match system database. Cloned or desynced drive!", is_error=True)

    @patch('auth_daemon.os.rename')
    @patch('auth_daemon.os.fsync')
    @patch('auth_daemon.os.path.exists', return_value=True)
    @patch('builtins.open', new_callable=mock_open)
    @patch('auth_daemon.log')
    def test_successful_verify_and_roll(self, mock_log, mock_file, mock_exists, mock_fsync, mock_rename):
        """Test a successful login: keys match, new keys generated, written atomically."""
        valid_secret = "my_secure_secret"
        valid_hash = hashlib.sha256(valid_secret.encode()).hexdigest()

        # Simulate reading the correct secret and hash
        handlers = (
            mock_open(read_data=valid_secret).return_value,
            mock_open(read_data=valid_hash).return_value,
            mock_open().return_value, # For writing new USB key
            mock_open().return_value  # For writing new DB hash
        )
        mock_file.side_effect = handlers

        self.assertTrue(auth_daemon.verify_and_roll())

        # Verify atomic write sequence (write -> fsync -> rename)
        self.assertEqual(mock_fsync.call_count, 2)
        self.assertEqual(mock_rename.call_count, 2)
        
        # Check that the files were renamed from .tmp to the actual paths
        mock_rename.assert_any_call(f"{auth_daemon.USB_KEY_PATH}.tmp", auth_daemon.USB_KEY_PATH)
        mock_rename.assert_any_call(f"{auth_daemon.SYSTEM_DB_PATH}.tmp", auth_daemon.SYSTEM_DB_PATH)

if __name__ == '__main__':
    unittest.main()