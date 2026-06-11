"""Brain Validator — 开源版 (stub)"""
class _BrainValidator:
    def validate(self, *a, **kw): return True
    def stats(self): return {}

_validator = _BrainValidator()
def get_brain_validator(): return _validator
