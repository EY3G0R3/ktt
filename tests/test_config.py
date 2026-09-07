import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ktt.config import (
    Config,
    DEFAULT_PHASE_TRACK_COLOR,
    DEFAULT_PHASE_TRACK_FORM,
    config_path,
    load_config,
    parse_config,
)


class ConfigTests(unittest.TestCase):
    def test_defaults_when_text_is_empty(self) -> None:
        self.assertEqual(parse_config(""), Config())

    def test_reads_phase_track_choices(self) -> None:
        config = parse_config('[phase_track]\nform = "full"\ncolor = "two_tone"\n')
        self.assertEqual(config.phase_track_form, "full")
        self.assertEqual(config.phase_track_color, "two_tone")

    def test_unknown_values_fall_back_per_key(self) -> None:
        config = parse_config('[phase_track]\nform = "hexagons"\ncolor = "gradient"\n')
        self.assertEqual(config.phase_track_form, DEFAULT_PHASE_TRACK_FORM)
        self.assertEqual(config.phase_track_color, "gradient")

    def test_wrong_types_and_broken_toml_fall_back(self) -> None:
        self.assertEqual(parse_config("[phase_track]\nform = 3\n"), Config())
        self.assertEqual(parse_config("phase_track = 'not a table'"), Config())
        self.assertEqual(parse_config("[phase_track\nform = "), Config())

    def test_missing_file_gives_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                load_config(Path(directory) / "absent.toml"), Config()
            )

    def test_file_is_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('[phase_track]\ncolor = "fixed"\n')
            config = load_config(path)
        self.assertEqual(config.phase_track_color, "fixed")
        self.assertEqual(config.phase_track_form, DEFAULT_PHASE_TRACK_FORM)
        self.assertEqual(DEFAULT_PHASE_TRACK_COLOR, "phase")

    def test_config_path_honors_xdg_config_home(self) -> None:
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/tmp/xdg-test"}):
            self.assertEqual(
                config_path(), Path("/tmp/xdg-test/ktt/config.toml")
            )


if __name__ == "__main__":
    unittest.main()
