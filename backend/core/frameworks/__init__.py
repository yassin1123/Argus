"""Consulting-frameworks layer — Phase 2 / Week 8.

Holds structural and prose-level QA checkers that run after the writer
produces a memo. Each framework module is independently importable so
new ones (MECE, SCQA, etc.) can land without touching existing code.

The Week 8 / Day 1 introduction is ``pyramid``: a two-stage Pyramid
Principle check (cheap structural pre-check + small-model LLM judge).
"""
