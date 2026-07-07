"""插件自动加载 — 开源版"""
def auto_activate_builtins(kernel=None):
    """开源版: 无内置插件"""
    import logging
    logging.getLogger("meshctx").info("Running in open-source stub mode — no built-in plugins")
    return 0
