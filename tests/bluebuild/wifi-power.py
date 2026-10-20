import importlib.machinery
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'files/system/usr/libexec/finite/wifi-ac-power'
loader = importlib.machinery.SourceFileLoader('wifi_power', str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
policy = importlib.util.module_from_spec(spec)
loader.exec_module(policy)

class WifiPower(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.supplies = self.root / 'power'
        self.net = self.root / 'net'
        self.supplies.mkdir()
        self.net.mkdir()
        (self.net / 'wlan0/wireless').mkdir(parents=True)

    def supply(self, name, **values):
        root = self.supplies / name
        root.mkdir()
        for key, value in values.items():
            (root / key).write_text(value)

    def test_battery_and_external_device_do_not_count_as_ac(self):
        self.supply('BAT0', type='Battery', online='1')
        self.supply('mouse', type='USB', scope='Device', online='1')
        self.assertEqual(policy.desired_mode(self.supplies), 'on')

    def test_online_ac_and_disconnected_ac(self):
        self.supply('AC', type='Mains', online='1')
        self.assertEqual(policy.desired_mode(self.supplies), 'off')
        (self.supplies / 'AC/online').write_text('0')
        self.assertEqual(policy.desired_mode(self.supplies), 'on')

    def invoke(self, current, set_returncode=0):
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            if 'get' in args:
                return subprocess.CompletedProcess(args, 0, f'Power save: {current}\n', '')
            return subprocess.CompletedProcess(args, set_returncode, '', 'adapter unavailable')
        def path(value):
            return {'/sys/class/net': self.net, '/sys/class/power_supply': self.supplies}[value]
        with patch.object(policy, 'Path', side_effect=path), patch.object(policy.subprocess, 'run', side_effect=run), patch.object(policy.sys, 'argv', ['wifi-ac-power']):
            result = policy.main()
        return result, calls

    def test_matching_policy_does_not_write(self):
        result, calls = self.invoke('on')
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 1)

    def test_transition_applies_final_policy_and_reports_failure(self):
        result, calls = self.invoke('off')
        self.assertEqual(result, 0)
        self.assertEqual(calls[-1][-3:], ['set', 'power_save', 'on'])
        result, _ = self.invoke('off', set_returncode=1)
        self.assertEqual(result, 1)

if __name__ == '__main__':
    unittest.main()
