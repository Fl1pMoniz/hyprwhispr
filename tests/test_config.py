import json

from hyprwhispr import config, speech


def test_default_model_is_multilingual():
    assert config.DEFAULTS["whisper_model"].endswith("ggml-small.bin")
    assert not config.DEFAULTS["whisper_model"].endswith(".en.bin")


def test_default_language_is_auto_detection():
    assert config.DEFAULTS["language"] is None
    assert speech.resolve_language(config.DEFAULTS["language"]) == ("auto", None)


def test_missing_language_in_config_defaults_to_auto(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text("{}")
    assert config.load_config(cfg_file)["language"] is None


def test_explicit_english_language_is_preserved(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"language": "en"}))
    assert config.load_config(cfg_file)["language"] == "en"


def test_existing_english_only_config_still_loads(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "language": "en",
        "whisper_model": "/path/to/ggml-small.en.bin",
    }))
    cfg = config.load_config(cfg_file)
    assert cfg["language"] == "en"  # backward compatible
    assert cfg["whisper_model"].endswith("ggml-small.en.bin")


def test_custom_model_path_is_preserved(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"whisper_model": "/custom/ggml-medium.bin"}))
    assert config.load_config(cfg_file)["whisper_model"] == "/custom/ggml-medium.bin"


def test_missing_model_key_uses_multilingual_default(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text("{}")
    assert config.load_config(cfg_file)["whisper_model"].endswith("ggml-small.bin")
