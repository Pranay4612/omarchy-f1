"""Lifecycle tests: safe cache clearing and self-termination on removal.

The marketplace installs by cloning this directory and removes it by deleting
it, so the service has to notice and leave. These tests cover the two pieces
that makes that safe: the check that decides the plugin is gone, and the cache
clearance that has to refuse to delete anything it does not own.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from f1 import cache
from f1.service import _plugin_still_installed, _remove_own_cache


class TestCacheClearanceGuards(unittest.TestCase):
    """The cache path is built from environment variables, so the guard is the
    only thing standing between "clear my cache" and "delete a directory"."""

    def setUp(self):
        self._old_cache_home = os.environ.get("XDG_CACHE_HOME")
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.environ["XDG_CACHE_HOME"] = str(self.root)
        cache.ensure_dirs()
        # A file to prove the namespace is really removed, not just emptied.
        (self.root / "omarchy" / "f1" / "state.json").write_text("{}")
        (self.root / "omarchy" / "other-plugin").mkdir(parents=True, exist_ok=True)
        (self.root / "omarchy" / "other-plugin" / "keep.txt").write_text("keep me")

    def tearDown(self):
        if self._old_cache_home is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = self._old_cache_home
        self.tmp.cleanup()

    def test_removes_only_its_own_namespace(self):
        self.assertTrue(_remove_own_cache(lambda *a: None))
        self.assertFalse((self.root / "omarchy" / "f1").exists())
        # A sibling plugin's cache is none of our business.
        self.assertTrue((self.root / "omarchy" / "other-plugin" / "keep.txt").exists())

    def test_refuses_when_the_cache_root_itself_would_be_deleted(self):
        # Point the cache root at the parent of omarchy/f1, so the namespace
        # resolves to something that is not <root>/omarchy/f1.
        os.environ["XDG_CACHE_HOME"] = str(self.root / "omarchy" / "f1")
        self.assertFalse(_remove_own_cache(lambda *a: None))
        self.assertTrue((self.root / "omarchy" / "f1").exists())

    def test_refuses_a_symlinked_namespace(self):
        # A link planted where the namespace belongs must not redirect the
        # deletion. The decoy is deliberately also named "omarchy/f1" so the
        # path-shape check passes and only the symlink check can stop it --
        # otherwise this test would pass for the wrong reason.
        decoy = self.root / "decoy" / "omarchy" / "f1"
        decoy.mkdir(parents=True)
        (decoy / "precious.txt").write_text("do not delete me")
        shutil.rmtree(self.root / "omarchy" / "f1")
        (self.root / "omarchy" / "f1").symlink_to(decoy)
        self.assertFalse(_remove_own_cache(lambda *a: None))
        self.assertTrue((decoy / "precious.txt").exists())
        self.assertTrue((self.root / "omarchy" / "f1").is_symlink())

    def test_refuses_an_unexpected_namespace_name(self):
        # Guard the name check itself by pointing the module's cache root at a
        # directory of the right depth but the wrong name.
        original = cache.cache_root
        try:
            cache.cache_root = lambda: self.root / "omarchy" / "notf1"
            (self.root / "omarchy" / "notf1").mkdir(parents=True)
            self.assertFalse(_remove_own_cache(lambda *a: None))
            self.assertTrue((self.root / "omarchy" / "notf1").exists())
        finally:
            cache.cache_root = original

    def test_missing_namespace_is_not_an_error(self):
        shutil.rmtree(self.root / "omarchy" / "f1")
        self.assertFalse(_remove_own_cache(lambda *a: None))


class TestLivenessCheck(unittest.TestCase):
    def test_the_real_installation_is_present(self):
        # We are running from inside the plugin, so this must be true. If it
        # ever is not, every lifetime check in the test suite is meaningless.
        self.assertTrue(_plugin_still_installed())

    def test_detection_keys_on_the_manifest(self):
        from f1.service import PLUGIN_ROOT

        self.assertTrue((PLUGIN_ROOT / "manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
