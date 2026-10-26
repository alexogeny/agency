import unittest
from unittest.mock import patch

from Tests.housekeeping_fixtures import HousekeepingProviderFixture


class HousekeepingRetentionScalingTests(HousekeepingProviderFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.provider = self.tool.provider_helpers()

    def release_items(self, size):
        paths = [self.release(f'0.{index}.0') for index in range(size)]
        current = self.releases.parent / 'current'
        current.symlink_to(paths[-1])
        items = []
        for path in paths:
            info = path.stat()
            items.append(dict(self.provider.proposal(path, self.home), path=str(path),
                              home=str(self.home), scan_complete=True,
                              identity={'device': info.st_dev, 'inode': info.st_ino}))
        return items, current, paths

    def test_one_retention_scan_per_tree_per_inspection(self):
        items, current, paths = self.release_items(16)
        with patch.object(self.provider, '_codex_retention', wraps=self.provider._codex_retention) as retention, \
             patch.object(self.provider.projects, 'mount_paths', return_value=set()), \
             patch.object(self.provider.projects, 'inspect_processes', return_value={'blocked': {}, 'uninspected_processes': 0}):
            report = self.provider.report_actions(items)
            self.assertEqual(len(report['blocked']), 2)
            self.assertEqual(retention.call_count, 1)
            current.unlink()
            current.symlink_to(paths[2])
            updated = self.provider.report_actions(items)
            self.assertEqual(len(updated['blocked']), 15)
            self.assertEqual(retention.call_count, 2)

    def test_removal_revalidates_retention_under_install_guard(self):
        items, current, paths = self.release_items(4)
        self.write(self.releases.parent / 'install.lock', b'')
        original_guard = self.provider._install_guard

        def guard(parent):
            current.unlink()
            current.symlink_to(paths[0])
            return original_guard(parent)

        with patch.object(self.provider, '_install_guard', side_effect=guard), \
             patch.object(self.provider.projects, 'mount_paths', return_value=set()), \
             patch.object(self.provider.projects, 'inspect_processes', return_value={'blocked': {}, 'uninspected_processes': 0}), \
             patch.object(self.provider, '_remove') as remove:
            with self.assertRaisesRegex(RuntimeError, 'current'):
                self.provider.execute(items[0])
        remove.assert_not_called()
        self.assertTrue(paths[0].exists())
