# Larger VN casts

The selected roster supports **20 NPCs**. Saved psychological identities remain
bounded separately at 32 to allow selection changes without deleting characters.
The default active limit is **3**; Standard remains the overall feature default.

One perception request considers the present selected roster. Directly addressed
or involved participants receive priority. In a larger cast, if such participants
are found, only those participants are processed. Spare places are not filled
merely to make background characters speak. If no direct participants are found,
the still-present participants of the last completed turn retain conversational
focus. If that group is absent, least recently processed present characters are
selected. A short reply does not randomly transfer the conversation to bystanders. If the whole
present cast fits the limit, all are processed.

The engagement classification is model-based. IDs and exact quotes are checked,
but a model can still misattribute an address or overlook a participant. Ambiguity
must be labelled conservatively. This needs live calibration, particularly for
pronouns and group addresses. No language-specific name matcher is used.

If direct participants exceed the active limit, preparation stops visibly before
individual cognitive calls. It never silently samples that group or falls back to
uncontrolled dialogue. Increase the limit/budget or split the interaction. The
shared perception call may already have been spent identifying the overflow.

## Inactive characters

Inactive or absent characters retain their identity, psychological history and
goals. Rotation updates only after a reviewed reply commits; failed turns do not
advance it. Rewind/fork invalidate scheduling information as appropriate.

The narration contract forbids new dialogue, decisions or private psychological
changes for present inactive controlled NPCs. Review checks that boundary; heard
speech from an inactive controlled speaker is also rejected structurally. This
remains a fallible semantic check, not an omniscient proof of every sentence.

Inactive characters are **not** continuously psychologically simulated and do not
automatically remember every missed conversation. When activated they observe
their current authoritative state; intervening causes are not invented. The shared
review retains at most twelve heard passages in total, even with twenty active
NPCs. This bounds memory writes but can omit conversational details.

## Cost controls

For `A` active NPCs, successful live control normally uses `A + 2` CHPM calls:
one perception, `A` proposals and one review. Reserve one shared proposal retry
and two more for narration repair and repeat review. The ordinary narrator call is separate. Thus three active NPCs
reserve 8 CHPM calls; twenty reserve 25. Unused reserve is not spent. Lower actual
participation costs less. Provider retries can add physical calls and cost.

Set Active NPCs per turn to 20 for full processing. Requests are sequential and
the reply is buffered until review. Large casts require larger shared schemas,
output allowance and narrator/reviewer context. Settings permit explicit limits
up to 192,000 input characters and 8,192 output tokens; defaults are unchanged.
The provider's own smaller token/context limits still apply. There is no automatic
budget increase and no guarantee that a small model can handle the largest cast.

These limits count characters or tokens as labelled; characters are not token
measurements. Use the evaluation matrix to measure latency and provider-reported
usage before choosing a production setting.
