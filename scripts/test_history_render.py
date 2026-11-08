"""Compatibility entry point for the standalone history renderer."""

if __package__ in {None, ""}:
    from test_history.render import main
else:
    from scripts.test_history.render import main

if __name__ == "__main__":
    main()
