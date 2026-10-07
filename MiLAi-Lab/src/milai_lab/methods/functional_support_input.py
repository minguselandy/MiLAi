"""Opt-in source-first working input guidance; no extraction or semantic certification."""

MAINTENANCE_LIMIT_PROMPT = """
Semantic proposal allowance: one initial proposal plus one revision for this public
request and actual target record. All new creations conservatively share one request
allowance when independent matters cannot be established. Changing wording, source
order or tool-call ID cannot reset it. Exact rejected inputs reuse the original result.
The second proposal must address a real evidence gap, preserving necessary limits;
do not remove a supported qualification merely to bypass review. Unresolved work stays
pending, not saved. A new explicit user request can start a fresh checked attempt.
Never repeat business effects to repair a memory review or final-answer failure.
"""

SUPPORT_INPUT_PROMPT = """
Before composing a new assertion or correction, separate the current instruction,
the exact existing record, and the original bodies that support the changed meaning.
For a nontrivial correction, mixed context/outcome, or unclear qualification, use
read_support_context with selected fragment handles and the actual read_handle if any.
This displays the old record and chosen originals; it does not approve the change.
You can also use already delivered complete originals or ordinary reads. Missing
adjacent conditions require a real source/page read within the existing allowance.

Start from the supported proposition and make only the requested change. Preserve
its necessary subject, occurrence, exceptions, uncertainty and normative strength.
An unknown start time remains unknown: neither a proposal nor its capture date proves
the new value is currently effective, and missing evidence does not prove the old value
is still effective. A selected explicit cancellation can remove a prior restriction.
The prior field's support covers unchanged meaning only. Context displayed elsewhere
is not selected support: if the assertion combines situation and observed outcome,
select originals supporting both. Requests never prove their own successful execution.

Use plain source-grounded wording. Do not add acronym expansions, technical causes,
recommendations, chapter numbers or stronger normative claims absent from the sources.
When review feedback conflicts with the actual originals, inspect it; do not delete a
necessary qualification merely to obtain a supported verdict. Pending is not saved.
No extra analyst model, exhaustive inferred limit list or source substitution is implied.
"""
