from hyprwhispr import validation


def test_args_ok_accepts_short_strings():
    assert validation.args_ok("hello", 10)


def test_args_ok_rejects_non_strings():
    assert not validation.args_ok(123)
    assert not validation.args_ok(None)


def test_args_ok_enforces_length():
    assert not validation.args_ok("x" * 11, 10)


def test_non_empty():
    assert validation.non_empty("kitty")
    assert not validation.non_empty("   ")
    assert not validation.non_empty("")


def test_valid_package_accepts_normal_names():
    assert validation.valid_package("firefox")
    assert validation.valid_package("python3.12")
    assert validation.valid_package("gcc-c++")


def test_valid_package_rejects_shell_metacharacters():
    for bad in ["firefox; rm -rf /", "a && b", "pkg | cat", "$(whoami)", "a`b`", "../etc"]:
        assert not validation.valid_package(bad), bad
