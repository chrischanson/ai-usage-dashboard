def create_parser(**kwargs):
    from parsers.opencode import OpenCodeParser
    from config import load_config
    return OpenCodeParser(timeout=load_config().subprocess_timeout)
