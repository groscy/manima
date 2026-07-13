"""The MANIMA core: domain types, the job state machine, the generate pipeline, the
escalation gate, hashing, and the AST validator. Pure orchestration — it depends only
on the port Protocols in ``core.ports`` and imports no adapter (design D1).
"""
