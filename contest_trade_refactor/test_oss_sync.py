import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.oss_sync import (
    iter_local_files,
    load_project_dotenv,
    normalize_oss_endpoint,
    object_key_for_path,
    oss_config_from_env,
)


class TestOssSyncHelpers(unittest.TestCase):
    def test_normalize_endpoint_adds_https(self):
        self.assertEqual(
            normalize_oss_endpoint("oss-cn-beijing.aliyuncs.com"),
            "https://oss-cn-beijing.aliyuncs.com",
        )
        self.assertEqual(
            normalize_oss_endpoint("https://oss-cn-beijing.aliyuncs.com"),
            "https://oss-cn-beijing.aliyuncs.com",
        )

    def test_object_key_uses_posix_paths(self):
        root = Path("/tmp/market")
        path = root / "stocks" / "qfq" / "600519.pkl"
        self.assertEqual(
            object_key_for_path(root, path, "market-bars"),
            "market-bars/stocks/qfq/600519.pkl",
        )

    def test_iter_local_files_skips_hidden_and_tmp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            keep = root / "stocks" / "600519.pkl"
            hidden = root / ".cache" / "skip.pkl"
            tempf = root / "stocks" / "600519.pkl.tmp"
            keep.parent.mkdir(parents=True, exist_ok=True)
            hidden.parent.mkdir(parents=True, exist_ok=True)
            keep.write_text("x", encoding="utf-8")
            hidden.write_text("y", encoding="utf-8")
            tempf.write_text("z", encoding="utf-8")
            self.assertEqual(list(iter_local_files(root)), [keep])

    def test_oss_config_from_env_requires_values(self):
        with patch.dict(os.environ, {}, clear=False):
            for key in ["OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET", "OSS_BUCKET", "OSS_ENDPOINT"]:
                os.environ.pop(key, None)
            with self.assertRaises(ValueError):
                oss_config_from_env()

    def test_oss_config_from_env_reads_prefix(self):
        with patch.dict(
            os.environ,
            {
                "OSS_ACCESS_KEY_ID": "id",
                "OSS_ACCESS_KEY_SECRET": "secret",
                "OSS_BUCKET": "bucket",
                "OSS_ENDPOINT": "oss-cn-beijing.aliyuncs.com",
                "OSS_PREFIX": "bars/prod",
            },
            clear=False,
        ):
            cfg = oss_config_from_env()
        self.assertEqual(cfg.endpoint, "https://oss-cn-beijing.aliyuncs.com")
        self.assertEqual(cfg.normalized_prefix, "bars/prod")

    def test_load_project_dotenv_does_not_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("OSS_BUCKET=from-file\nOSS_PREFIX=from-file\n", encoding="utf-8")
            with patch.dict(os.environ, {"OSS_BUCKET": "already-set"}, clear=False):
                os.environ.pop("OSS_PREFIX", None)
                load_project_dotenv(env_path)
                self.assertEqual(os.environ["OSS_BUCKET"], "already-set")
                self.assertEqual(os.environ["OSS_PREFIX"], "from-file")
            os.environ.pop("OSS_PREFIX", None)


if __name__ == "__main__":
    unittest.main()
