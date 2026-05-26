from cc_history.slug import slug_to_path, path_to_slug


def test_slug_to_path_basic():
    assert slug_to_path("-Users-gauravdhir") == "/Users/gauravdhir"


def test_slug_to_path_nested():
    assert slug_to_path("-Users-gauravdhir-Documents-Foo") == "/Users/gauravdhir/Documents/Foo"


def test_slug_to_path_with_dashes_in_dir():
    # Claude Code encodes literal dashes as dashes too — we can't reliably distinguish.
    # Confirm the documented behavior: every dash becomes a slash.
    assert slug_to_path("-Users-foo-my-project") == "/Users/foo/my/project"


def test_path_to_slug_basic():
    assert path_to_slug("/Users/gauravdhir") == "-Users-gauravdhir"


def test_path_to_slug_roundtrip():
    for path in ["/Users/x", "/Users/x/Documents/Bar"]:
        assert slug_to_path(path_to_slug(path)) == path
