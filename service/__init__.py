"""Production service wrapping the takeoff pipeline as async, idempotent jobs.

Only ``service.takeoff.pipeline_adapter`` imports the pipeline (``src.takeoff``); the rest of
this package is web/queue/storage plumbing. See docs/takeoff_service_design.md.
"""
