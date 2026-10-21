"""Step 2 — Rule-Based Classification Package.

Components:
  - schema_reader:    CSV/JSON schema ingestion & metadata extraction.
  - name_normalizer:  Column-name normalisation, abbreviation expansion, tokenisation.
  - rule_classifier:  YAML-rule loading, group/type attribution, contextual scoring.
  - ambiguity_handler: Unknown detection, conflict resolution, review flagging.
"""
from __future__ import annotations
