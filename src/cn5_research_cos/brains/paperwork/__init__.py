"""paperwork scripts-as-toolbox adapter (P4a).

The cockpit consumes paperwork's deterministic ``scripts/`` (pdf_outline_scan,
extract_page_range_pdf, pdf2md) via subprocess — it does NOT drive paperwork's
agentic ``skills/``. paperwork is an EXTERNAL gerrit dependency resolved at
runtime (``locate.find_paperwork_home``); its scripts are NEVER vendored here.
"""
