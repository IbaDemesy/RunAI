def pytest_addoption(parser):
    parser.addoption(
        "--update-golden", action="store_true", default=False,
        help="Rewrite additive events.v1 and mission.v2 key-path goldens.",
    )
