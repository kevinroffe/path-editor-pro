def test_backend_modules_importable():
    import autopath  # noqa: F401
    import app  # noqa: F401
    assert True
