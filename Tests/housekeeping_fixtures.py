"""Application-cleanup fixture data shared by provider and retention tests."""
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

from Tests.test_housekeeping import load_tool


class HousekeepingProviderFixture:
    def setUp(self):
        super().setUp()
        self.tool = load_tool()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.web = self.home / '.local/share/web-research/profiles'
        self.releases = self.home / '.codex/packages/app-server-daemon/releases'

    def write(self, path, data=b'fixture'):
        path = self.home / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def profile(self, name='task', **metadata):
        root = self.web / name
        self.write(root / 'cache2/entries/cache', b'x' * 8192)
        self.write(root / 'startupCache/startupCache.8.little', b'y' * 4096)
        self.write(root / 'cookies.sqlite', b'preserve cookies')
        self.write(root / 'storage/default/site/data', b'preserve site data')
        if metadata:
            value = dict(schema_version=1, owner='web-research', purpose='task', pinned=False,
                         last_used_at=time.time() - 40 * 86400, completed_at=time.time() - 40 * 86400)
            value.update(metadata)
            self.write(Path(str(root) + '.agency.json'), json.dumps(value).encode())
        return root

    def plan(self):
        helper = self.tool.project_helpers()
        with patch.object(helper, 'inspect_processes', return_value={'blocked': {}, 'uninspected_processes': 0}):
            return self.tool.cleanup_plan(self.tool.scan(self.home, home=self.home, mount_points=set()))

    def applications(self):
        return self.plan()['application_candidates']

    def release(self, version):
        root = self.releases / (version + '-x86_64-unknown-linux-musl')
        self.write(root / 'bin/codex', b'binary')
        self.write(root / 'codex-package.json', json.dumps(dict(layoutVersion=1, version=version,
                   target='x86_64-unknown-linux-musl', variant='codex', entrypoint='bin/codex')).encode())
        return root
