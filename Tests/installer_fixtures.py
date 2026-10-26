"""Executable command stubs for disposable installer environments."""
import stat
import textwrap


class InstallerCommandFixture:
    def executable(self, name, source):
        path = self.bin / name
        path.write_text(textwrap.dedent(source).lstrip())
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path
