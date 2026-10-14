#!/usr/bin/env python3
"""Exercise private-console unlock parsing without launching a VM."""
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('unlock_console', ROOT / 'scripts/bluebuild/unlock-vm.py')
unlock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(unlock)

# Exact prompt excerpt from main run 38626712683, failed generic rollback.
# Kernel output interrupted "passphrase" before cryptsetup could read the key.
ROLLBACK_PROMPT = (
    b'Please enter pas[    3.161672] [drm] Framebuffer size 16384 kB @ 0x80000000, mmio @ 0x81083000.\r\n'
    b'sphrase for disk luks-6769f67f-104e-4339-b5ff-650e0ceab68b: (press TAB for no echo) \x1b[0m'
    b'[    3.169889] bochs-drm 0000:00:01.0: [drm] Registered 1 planes with drm panic\r\n'
)


class UnlockConsole(unittest.TestCase):
    secret = b'a1' * 32

    def exercise(self, chunks, accepted=True):
        connection = Mock()
        connection.recv.side_effect = [*chunks, b'']
        log, output = io.BytesIO(), io.BytesIO()
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / 'unlock.log'
            if accepted:
                unlock.relay(connection, self.secret, log, marker, output)
                connection.sendall.assert_called_once_with(self.secret + b'\r')
                self.assertEqual(marker.read_text(), 'Unlock submitted over private serial console\n')
            else:
                with self.assertRaisesRegex(RuntimeError, 'never requested'):
                    unlock.relay(connection, self.secret, log, marker, output)
                connection.sendall.assert_not_called()
                self.assertFalse(marker.exists())
        self.assertEqual(log.getvalue(), output.getvalue())
        self.assertNotIn(self.secret, log.getvalue())
        return log.getvalue()

    def test_actual_interleaved_rollback_prompt_keeps_raw_log(self):
        self.assertIsNone(unlock.PROMPT.search(ROLLBACK_PROMPT))
        self.assertEqual(self.exercise([ROLLBACK_PROMPT]), ROLLBACK_PROMPT)

    def test_kernel_timestamp_message_and_line_ending_can_fragment(self):
        positions = [ROLLBACK_PROMPT.index(b'[') + 1,
                     ROLLBACK_PROMPT.index(b'3.161672') + 3,
                     ROLLBACK_PROMPT.index(b'Framebuffer') + 5,
                     ROLLBACK_PROMPT.index(b'\r\n') + 1,
                     ROLLBACK_PROMPT.index(b'sphrase') + 3]
        for position in positions:
            with self.subTest(position=position):
                self.assertEqual(self.exercise([ROLLBACK_PROMPT[:position], ROLLBACK_PROMPT[position:]]),
                                 ROLLBACK_PROMPT)

    def test_bytewise_console_reads_and_fragmented_echo_stay_redacted(self):
        echo = self.secret + b'\r\n'
        log = self.exercise([bytes([byte]) for byte in ROLLBACK_PROMPT + echo])
        self.assertEqual(log, ROLLBACK_PROMPT + b'[REDACTED]\r\n')

    def test_repeated_interleaved_prompt_submits_only_once(self):
        self.assertEqual(self.exercise([ROLLBACK_PROMPT, ROLLBACK_PROMPT]), ROLLBACK_PROMPT * 2)

    def test_multiple_complete_kernel_records_reconstruct_prompt(self):
        prompt = (b'Please enter pas[  1.000001] message\n[  1.000002] another\r\n'
                  b'sphrase for di[  1.000003] third\r\nsk QEMU (luks-test): ')
        self.assertEqual(self.exercise([prompt]), prompt)

    def test_fragmented_kernel_record_cannot_submit_a_quoted_prompt(self):
        quoted = b'[  1.000001] quoted: Please enter passphrase for disk luks-test: '
        chunks = [bytes([byte]) for byte in quoted] + [b'continued\r', b'\n']
        self.assertEqual(self.exercise(chunks, accepted=False), quoted + b'continued\r\n')

    def test_real_prompt_before_unfinished_kernel_record_still_unlocks(self):
        prompt = b'Please enter passphrase for disk luks-test: '
        unfinished = b'[  1.000001] an unfinished kernel message'
        self.assertEqual(self.exercise([prompt + unfinished]), prompt + unfinished)

    def test_only_complete_timestamped_records_are_ignored(self):
        for data in [b'Please enter pas[  1.000001] unfinished record sphrase for disk luks-test: ',
                     b'Please enter pas[debug] message\r\nsphrase for disk luks-test: ',
                     b'[  1.000001] Please enter passphrase for disk luks-test:\r\n',
                     b'Please enter passphrase for disk luks-test',
                     b'Please enter passphrase for disk luks-test\n:',
                     b'finite login: ']:
            with self.subTest(data=data):
                self.assertEqual(self.exercise([data], accepted=False), data)

    def test_detection_window_remains_bounded_after_noisy_boot(self):
        chunks = [b'x' * 4096] * 8 + [ROLLBACK_PROMPT]
        with patch.object(unlock, 'disk_prompt', wraps=unlock.disk_prompt) as detect:
            self.assertEqual(self.exercise(chunks), b''.join(chunks))
        self.assertTrue(detect.called)
        self.assertTrue(all(len(call.args[0]) <= unlock.PROMPT_WINDOW for call in detect.call_args_list))


if __name__ == '__main__':
    unittest.main()
