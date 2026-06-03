"""Notification surface for the cockpit (P5c).

Currently one channel: ``email.notify_supplement_needed`` — an Outlook-COM email
telling the user which decision-critical claims could not be verified and how to
supplement them (text via ``cos steer`` or a document dropped into the run's
``reference/`` folder). Fail-soft: a send failure logs a VISIBLE warning and
returns False; the HumanTask the supplement maps to is still recorded by the loop,
so the need is never silently lost.
"""
from .email import build_supplement_email, notify_supplement_needed

__all__ = ["build_supplement_email", "notify_supplement_needed"]
