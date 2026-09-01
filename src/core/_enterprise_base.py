# -*- coding: utf-8 -*-
"""Enterprise stub 基础 — 开源库企业版占位 (2026-08-31)。

完整实现: 私有库 meshctx-enterprise (Proprietary)。
"""


class EnterpriseFeatureError(NotImplementedError):
    """企业版功能未安装 (开源库 stub 占位)。"""
    def __init__(self, msg="Enterprise 功能已迁移至私有库 meshctx-enterprise (Proprietary)"):
        super().__init__(msg)


def _enterprise_stub(*a, **k):
    raise EnterpriseFeatureError()
