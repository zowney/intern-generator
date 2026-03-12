"""
Ollama-based event generator for the intern simulator.
Handles prompt construction and model interaction.
"""

import json
import re
from difflib import SequenceMatcher

import ollama


def get_available_models() -> list[str]:
    """Fetch list of locally available Ollama models."""
    try:
        response = ollama.list()
        models = [m.model for m in response.models]
        return models if models else ["llama3.2"]
    except Exception:
        return ["llama3.2"]


# ---------------------------------------------------------------------------
# Discipline descriptions — used to steer event generation
# ---------------------------------------------------------------------------

DISCIPLINE_GUIDANCE = {
    "Business": (
        "The Business intern is an INTELLIGENCE ANALYST. Their role is to "
        "receive intelligence briefings — fabricated but realistic events "
        "happening in the world — and analyze their significance to the project.\n\n"
        "CRITICAL: You MUST invent specific, detailed, fictional intelligence. "
        "Make up concrete details:\n"
        "- Specific dates (e.g., 'On February 3rd...')\n"
        "- Specific places (e.g., 'the port of Djibouti', 'the Strait of Malacca', "
        "'a facility outside Volgograd')\n"
        "- Specific organizations, vessels, units, or actors (invent names)\n"
        "- Specific numbers and measurements (e.g., '14 vessels', '37%% increase', "
        "'an estimated 2,400 metric tons')\n"
        "- Specific sources (e.g., 'commercial satellite imagery from January 28th', "
        "'intercepted communications', 'a leaked internal memo', 'OSINT forums', "
        "'a classified SIGINT report')\n\n"
        "The scenario should read like an intelligence cable or situational "
        "report — not a vague business brief. It should feel like something "
        "landed on the analyst's desk that morning.\n\n"
        "Examples of the KIND of event to generate (adapt to the project):\n"
        "- 'On January 15th, commercial satellite imagery captured 14 previously "
        "untracked cargo vessels clustered near the port of Berbera, Somalia. "
        "AIS data shows these vessels went dark 72 hours prior. Regional HUMINT "
        "assets report increased activity at a nearby warehouse complex.'\n"
        "- 'An intercepted communication between two known logistics firms "
        "references a shipment of dual-use components scheduled to transit "
        "through the Suez Canal on March 2nd. The manifest lists industrial "
        "generators, but the weight discrepancy suggests additional cargo.'\n"
        "- 'OSINT monitoring flagged a series of forum posts on a Telegram "
        "channel associated with maritime security. Multiple sources claim "
        "a new patrol route has been established off the coast of Yemen "
        "starting this month, contradicting official statements.'\n"
        "- 'A leaked budget document from a regional defense ministry shows "
        "a 340%% increase in procurement spending for coastal surveillance "
        "equipment over the past fiscal quarter.'\n\n"
        "The intern must figure out the 'so what?' — why it matters, what "
        "caused it, what it means for the project, and what to recommend. "
        "Do NOT provide the analysis. Present the raw intelligence and let "
        "the intern work.\n\n"
        "Every Business event should also require a short analysis deliverable: "
        "a concise situational-awareness or geopolitical impact report that "
        "explains why the event matters to the project."
    ),
    "Systems Engineer": (
        "The Systems Engineer intern works within a MODEL-BASED SYSTEMS ENGINEERING "
        "(MBSE) framework. Their events should present situations where the system "
        "model, architecture, or requirements need attention because of something "
        "that happened:\n\n"
        "Examples of the KIND of event to generate (adapt to the project):\n"
        "- 'The business team's analysis of the Somalia shipping activity suggests "
        "we need to handle 3x more data throughput than originally modeled. The "
        "current system architecture may not support this.'\n"
        "- 'A stakeholder review revealed that two subsystem interfaces are "
        "specifying conflicting data formats — one expects JSON, the other XML.'\n"
        "- 'The new compliance requirement identified by the business team "
        "needs to be traced through the system model to identify which "
        "components are affected.'\n"
        "- 'Testing found that the system's response time requirement (REQ-042) "
        "has no verification method defined in the model.'\n"
        "- 'A design review is in two weeks and the SysML activity diagrams "
        "for the alert processing pipeline do not reflect the latest changes.'\n\n"
        "Events should reflect MBSE thinking: model-driven, requirements-traceable, "
        "and focused on systems, interfaces, and traceability. When generated "
        "alongside Business events, the SE event should be a direct consequence "
        "of what Business discovered.\n\n"
        "Every Systems Engineer event should require a short engineering-change "
        "deliverable: requirement impact analysis, interface change proposal, "
        "or architecture update rationale tied to the scenario."
    ),
    "Developer": (
        "The Developer intern builds features and capabilities driven by project "
        "needs. Their events should present situations where new functionality "
        "is needed or existing code needs to change because of something happening "
        "on the project:\n\n"
        "Examples of the KIND of event to generate (adapt to the project):\n"
        "- 'The systems engineer has updated the architecture to handle the "
        "increased data throughput from the Somalia shipping activity. A new "
        "notification system needs to be built to alert analysts when activity "
        "spikes are detected.'\n"
        "- 'The interface conflict between subsystems means the data ingestion "
        "module needs a format adapter. The SE has provided updated ICDs.'\n"
        "- 'The new compliance requirement means we need to add audit logging "
        "to every API endpoint that touches sensitive data.'\n"
        "- 'Performance testing shows the dashboard query takes 12 seconds on "
        "large datasets. Users need it under 2 seconds.'\n"
        "- 'A teammate started building the alert pipeline but had to switch "
        "to another project. Their branch has partial work that needs to be "
        "picked up and completed.'\n\n"
        "Events should be about BUILDING or CHANGING things — new features, "
        "integrations, fixes, or improvements. When generated alongside SE "
        "events, the Developer event should stem from what the SE designed "
        "or discovered. Not every event requires code, but most should.\n\n"
        "Every Developer event should require a brief technical deliverable: "
        "for example a scaling approach memo, implementation tradeoff summary, "
        "or design note describing how to build the needed capability."
    ),
}

DISCIPLINE_ORDER = ["Business", "Systems Engineer", "Developer"]
LAST_GENERATION_WARNING: str | None = None


# ---------------------------------------------------------------------------
# Output JSON contract
# ---------------------------------------------------------------------------

REFERENCE_DEFENSE_FORMATS = {
    "CDRL": "Contract Data Requirements List",
    "DID": "Data Item Description",
    "CONOPS": "Concept of Operations",
    "ICD": "Interface Control Document",
    "SRD": "System Requirements Document",
    "TEMP": "Test and Evaluation Master Plan",
    "PDR": "Preliminary Design Review",
    "CDR": "Critical Design Review",
}

REFERENCE_CONTRACT_KEYWORDS = [
    "briefing",
    "memo",
    "report",
    "analysis",
]

EVENT_FORMAT = (
    "Output STRICT JSON only. Do not use markdown fences.\n\n"
    "Use exactly this top-level object shape:\n"
    "{\n"
    '  "events": [\n'
    "    {\n"
    '      "event_number": <integer>,\n'
    '      "title": "<short descriptive title>",\n'
    '      "discipline": "<Business|Systems Engineer|Developer>",\n'
    '      "scenario": "<1-3 paragraph scenario text>",\n'
    '      "deliverables": [\n'
    "        {\n"
    '          "artifact": "<what is submitted>",\n'
    '          "purpose": "<why it is needed>",\n'
    '          "required_contents": ["<exactly 5 plain-language bullets describing what to include>"],\n'
    '          "audience": "<intended reviewer/consumer>",\n'
    '          "potential_formats": ["<array of possible output formats, including acronyms and full names>"]\n'
    "        }\n"
    "      ]\n"
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    "- Never include tasks, steps, or solution hints.\n"
    "- Scenario must describe what happened, not how to solve it.\n"
    "- Deliverables must be concrete outputs and must vary event-to-event.\n"
    "- Artifact names must be specific and materially distinct from prior events.\n"
    "- Avoid reusing generic templates such as repeated risk assessment or briefing titles.\n"
    "- Favor diverse artifact forms across events (for example matrix, annex, register, watchlist, options memo, review package).\n"
    "- 'required_contents' must be an array of exactly 5 plain-language bullet strings.\n"
    "- Keep required_contents concise and intern-friendly (short checklist style).\n"
    "- 'required_contents' must not contain defense-acronym shorthand.\n"
    "- 'potential_formats' must be an array and should include both acronym and full-name options.\n"
    "- Every deliverable's potential_formats must include one defense format and one contract-style format.\n"
    "- Use plain, professional language with no emojis."
)

PROMPT_CLOSER = (
    "\n\nIMPORTANT: Do NOT ask questions or add commentary. "
    "Return JSON only. Your first character must be '{'."
)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def _build_system_prompt(mode: str, discipline: str | None = None) -> str:
    base = (
        "You are a project simulation engine. You ONLY output event content "
        "as strict JSON. You NEVER ask questions. You NEVER add commentary, "
        "introductions, or explanations. You NEVER say things like 'Let me know' "
        "or 'What kind of project'. You have all the information you need in the "
        "user message.\n\n"
        "Your SOLE job: read the project description provided and immediately "
        "output events in the exact JSON format specified. Start your "
        "response with '{' — nothing before it.\n\n"
        "You simulate a living, evolving project by generating events in sequence — "
        "things that HAPPEN — that interns must respond to. You are NOT "
        "generating task lists. You are generating realistic scenarios.\n\n"
        "WORLD-BUILDING: You MUST invent specific, concrete, fictional details "
        "for every event. Make up dates, locations, organization names, vessel "
        "names, report titles, personnel names, measurements, and sources. "
        "The events should feel like real intelligence reports or project "
        "dispatches — not vague summaries. The more specific and grounded "
        "the details, the better the simulation. Keep details plausible and "
        "clearly scenario-based; avoid presenting unverified claims as "
        "confirmed real-world facts.\n\n"
    )

    if mode == "all":
        base += (
            "KEY PRINCIPLE: Events cascade across disciplines. A real-world "
            "observation (Business) drives a system architecture change (Systems "
            "Engineer) which drives new development work (Developer).\n\n"
        )
    elif discipline:
        base += (
            f"You are generating events for the '{discipline}' discipline ONLY. "
            f"Do NOT generate events for any other discipline. Every event you "
            f"output must be for '{discipline}' and no other role.\n\n"
        )

    base += (
        "Rules:\n"
        "- Each event = one timeline step of work.\n"
        "- Present the SITUATION with specific, concrete details.\n"
        "- Do not tell the intern what to do — describe what happened.\n"
        "- Events should be realistic and appropriately scoped for an intern.\n"
        "- Use specific numbers only when they are clearly estimates or scenario observations.\n"
        "- Later events must build on consequences of earlier ones.\n"
        "- Do not use emojis anywhere.\n"
        "- Use plain, professional language.\n"
        "- NEVER include preamble, questions, or commentary.\n"
        "- Output must be valid JSON with a top-level 'events' array.\n"
        "- Event numbers must use integer numbering only.\n"
    )

    return base


def get_last_generation_warning() -> str | None:
    """Return warning text from last generation attempt, if any."""
    return LAST_GENERATION_WARNING


def _extract_json_payload(text: str) -> str:
    """Extract a JSON object payload from model text response."""
    stripped = text.strip()
    code_fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, re.DOTALL)
    if code_fence:
        return code_fence.group(1).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return stripped[start:end + 1].strip()
    return stripped


def _parse_events_json(text: str) -> tuple[list[dict], list[str], str]:
    """Parse generated JSON and return events, errors, and normalized JSON text."""
    payload_text = _extract_json_payload(text)
    errors: list[str] = []
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        return [], [f"Output is not valid JSON: {exc}"], payload_text

    if not isinstance(payload, dict):
        return [], ["Top-level JSON must be an object."], payload_text
    events = payload.get("events")
    if not isinstance(events, list):
        return [], ["Top-level key 'events' must be an array."], payload_text
    normalized = json.dumps(payload, ensure_ascii=True, indent=2)
    return events, errors, normalized


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _collect_prior_artifacts(previous_events: str | None) -> set[str]:
    if not previous_events:
        return set()
    events, _, _ = _parse_events_json(previous_events)
    artifacts: set[str] = set()
    for event in events:
        if isinstance(event, dict):
            for item in event.get("deliverables", []):
                if isinstance(item, dict):
                    artifact = item.get("artifact")
                    if isinstance(artifact, str) and artifact.strip():
                        artifacts.add(_normalize_text(artifact))
    return artifacts


def _format_contains_defense_reference(value: str) -> bool:
    lowered = value.lower()
    for acronym, full_name in REFERENCE_DEFENSE_FORMATS.items():
        if acronym.lower() in lowered or full_name.lower() in lowered:
            return True
    return False


def _artifact_similarity(left: str, right: str) -> float:
    """Approximate similarity between artifact names."""
    left_norm = _normalize_text(left)
    right_norm = _normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    ratio = SequenceMatcher(None, left_norm, right_norm).ratio()
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    overlap = (
        len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
        if left_tokens and right_tokens
        else 0.0
    )
    return max(ratio, overlap)


def _validate_output_shape(
    events: list[dict],
    mode: str,
    discipline: str | None,
    num_events: int,
    start_event: int,
    deliverables_per_event: int,
    previous_artifacts: set[str],
) -> tuple[bool, list[str]]:
    """
    Validate generated JSON for schema, continuity, discipline, and novelty.
    """
    errors: list[str] = []
    expected_events = list(range(start_event, start_event + num_events))
    allowed_disciplines = set(DISCIPLINE_ORDER)
    seen_artifacts: set[str] = set()
    seen_artifact_labels: list[tuple[int, int, str]] = []

    if not events:
        return False, ["No events were returned in 'events'."]

    event_records: list[tuple[int, str, dict]] = []
    for idx, event in enumerate(events, start=1):
        if not isinstance(event, dict):
            errors.append(f"Event {idx} must be an object.")
            continue
        event_number = event.get("event_number")
        title = event.get("title")
        event_discipline = event.get("discipline")
        scenario = event.get("scenario")
        deliverables = event.get("deliverables")
        if not isinstance(event_number, int):
            errors.append(f"Event {idx} has non-integer 'event_number'.")
            continue
        if not isinstance(title, str) or not title.strip():
            errors.append(f"Event {idx} is missing non-empty 'title'.")
        if event_discipline not in allowed_disciplines:
            errors.append(
                f"Event {idx} has invalid discipline '{event_discipline}'."
            )
        if not isinstance(scenario, str) or not scenario.strip():
            errors.append(f"Event {idx} is missing non-empty 'scenario'.")
        if not isinstance(deliverables, list):
            errors.append(f"Event {idx} 'deliverables' must be an array.")
            continue
        if len(deliverables) != deliverables_per_event:
            errors.append(
                f"Event {idx} expected {deliverables_per_event} deliverable(s), "
                f"got {len(deliverables)}."
            )
        event_records.append((event_number, str(event_discipline), event))

        for deliverable_idx, deliverable in enumerate(deliverables, start=1):
            if not isinstance(deliverable, dict):
                errors.append(
                    f"Event {idx} deliverable {deliverable_idx} must be an object."
                )
                continue
            for field in [
                "artifact",
                "purpose",
                "audience",
            ]:
                value = deliverable.get(field)
                if not isinstance(value, str) or not value.strip():
                    errors.append(
                        f"Event {idx} deliverable {deliverable_idx} has invalid "
                        f"'{field}'."
                    )

            artifact_raw = deliverable.get("artifact", "")
            artifact = _normalize_text(artifact_raw) if isinstance(artifact_raw, str) else ""
            if artifact:
                if artifact in seen_artifacts:
                    errors.append(
                        f"Event {idx} deliverable {deliverable_idx} repeats artifact "
                        f"'{artifact_raw}'."
                    )
                if artifact in previous_artifacts:
                    errors.append(
                        f"Event {idx} deliverable {deliverable_idx} reuses prior "
                        f"artifact '{artifact_raw}'."
                    )
                else:
                    for prior_artifact in previous_artifacts:
                        if _artifact_similarity(artifact, prior_artifact) >= 0.80:
                            errors.append(
                                f"Event {idx} deliverable {deliverable_idx} is too similar "
                                f"to prior artifact '{prior_artifact}'."
                            )
                            break
                for prev_event_idx, prev_deliverable_idx, prev_label in seen_artifact_labels:
                    if _artifact_similarity(artifact_raw, prev_label) >= 0.82:
                        errors.append(
                            f"Event {idx} deliverable {deliverable_idx} is too similar "
                            f"to event {prev_event_idx} deliverable {prev_deliverable_idx} "
                            f"('{artifact_raw}' vs '{prev_label}')."
                        )
                        break
                seen_artifacts.add(artifact)
                seen_artifact_labels.append((idx, deliverable_idx, artifact_raw))

            required_contents = deliverable.get("required_contents")
            if not isinstance(required_contents, list) or len(required_contents) != 5:
                errors.append(
                    f"Event {idx} deliverable {deliverable_idx} required_contents "
                    "must be an array of exactly 5 bullet strings."
                )
            elif not all(isinstance(item, str) and item.strip() for item in required_contents):
                errors.append(
                    f"Event {idx} deliverable {deliverable_idx} required_contents "
                    "must contain only non-empty strings."
                )
            else:
                for bullet in required_contents:
                    for acronym in REFERENCE_DEFENSE_FORMATS:
                        if acronym.lower() in bullet.lower():
                            errors.append(
                                f"Event {idx} deliverable {deliverable_idx} "
                                "required_contents should use plain language and avoid "
                                f"acronym '{acronym}'."
                            )
                            break

            potential_formats = deliverable.get("potential_formats")
            if not isinstance(potential_formats, list) or not potential_formats:
                errors.append(
                    f"Event {idx} deliverable {deliverable_idx} potential_formats "
                    "must be a non-empty array."
                )
                continue
            if not all(isinstance(item, str) and item.strip() for item in potential_formats):
                errors.append(
                    f"Event {idx} deliverable {deliverable_idx} potential_formats "
                    "must contain only non-empty strings."
                )
                continue
            joined_formats = " ".join(potential_formats)
            has_defense = _format_contains_defense_reference(joined_formats)
            has_contract = any(
                token.lower() in joined_formats.lower()
                for token in REFERENCE_CONTRACT_KEYWORDS
            )
            if not has_defense or not has_contract:
                errors.append(
                    f"Event {idx} deliverable {deliverable_idx} potential_formats "
                    "must include both a defense format (acronym or full name) "
                    "and a contract-style format."
                )

    if mode in {"single", "set"}:
        if len(event_records) != num_events:
            errors.append(
                f"Expected {num_events} event(s), found {len(event_records)}."
            )
        got_events = [event_number for event_number, _, _ in event_records]
        if got_events != expected_events:
            errors.append(
                f"Event numbering mismatch. Expected {expected_events}, got {got_events}."
            )
        if discipline:
            for idx, (_, record_discipline, _) in enumerate(event_records, start=1):
                if record_discipline != discipline:
                    errors.append(
                        f"Event {idx} has discipline '{record_discipline}', "
                        f"expected '{discipline}'."
                    )
    else:
        expected_count = num_events * 3
        if len(event_records) != expected_count:
            errors.append(
                f"Expected {expected_count} events for all-disciplines mode, "
                f"found {len(event_records)}."
            )
        event_counts: dict[int, int] = {}
        event_to_disciplines: dict[int, set[str]] = {}
        event_discipline_order: dict[int, list[str]] = {}
        for event_number, disc, _ in event_records:
            event_counts[event_number] = event_counts.get(event_number, 0) + 1
            event_to_disciplines.setdefault(event_number, set()).add(disc)
            event_discipline_order.setdefault(event_number, []).append(disc)

        for event_number in expected_events:
            if event_counts.get(event_number, 0) != 3:
                errors.append(
                    f"Event {event_number} should appear 3 times, found "
                    f"{event_counts.get(event_number, 0)}."
                )
            found = event_to_disciplines.get(event_number, set())
            if found != set(DISCIPLINE_ORDER):
                errors.append(
                    f"Event {event_number} discipline set mismatch. "
                    f"Expected {DISCIPLINE_ORDER}, got {sorted(found)}."
                )
            order = event_discipline_order.get(event_number, [])
            if order != DISCIPLINE_ORDER:
                errors.append(
                    f"Event {event_number} discipline order mismatch. "
                    f"Expected {DISCIPLINE_ORDER}, got {order}."
                )

    return len(errors) == 0, errors


def _build_repair_prompt(
    original_prompt: str,
    invalid_output: str,
    errors: list[str],
) -> str:
    """Prompt used to repair invalid output format/content boundaries."""
    joined_errors = "\n".join(f"- {error}" for error in errors)
    return (
        "Your previous answer violated JSON schema or consistency constraints.\n\n"
        "You MUST rewrite the full answer from scratch using the original task.\n"
        "Do not explain. Do not apologize. Output only corrected JSON.\n\n"
        "--- ORIGINAL TASK ---\n"
        f"{original_prompt}\n"
        "--- END ORIGINAL TASK ---\n\n"
        "--- VALIDATION ERRORS TO FIX ---\n"
        f"{joined_errors}\n"
        "--- END VALIDATION ERRORS ---\n\n"
        "--- INVALID OUTPUT (FOR REFERENCE) ---\n"
        f"{invalid_output}\n"
        "--- END INVALID OUTPUT ---\n\n"
        "Now provide only the corrected JSON object."
    )


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------

def _add_previous_events_context(prompt: str, previous_events: str | None) -> str:
    """Append previous event history to the prompt if provided."""
    if previous_events:
        prompt += (
            "\n\n--- PREVIOUS EVENTS ---\n"
            "The following events have already occurred on this project. "
            "Your new event(s) MUST build on, reference, or be a consequence "
            "of what has already happened. Do not repeat previous events. "
            "Advance the project timeline forward. Avoid reusing prior deliverable "
            "artifact names.\n\n"
            f"{previous_events}\n"
            "--- END PREVIOUS EVENTS ---\n"
        )
    return prompt


def _add_feedback_context(prompt: str, feedback: str | None) -> str:
    """Append user feedback to steer the generation."""
    if feedback and feedback.strip():
        prompt += (
            "\n\n--- FEEDBACK ---\n"
            "The facilitator has provided the following feedback. "
            "Take this into account when generating the event(s):\n\n"
            f"{feedback.strip()}\n"
            "--- END FEEDBACK ---\n"
        )
    return prompt


def _add_cross_reference_instruction(prompt: str) -> str:
    """Add instruction for same-event-number events to reference each other."""
    prompt += (
        "\n\nCROSS-DISCIPLINE REFERENCES: Events with the same event_number MUST "
        "explicitly reference each other and form a causal chain. The Business "
        "event presents a real-world observation or development. The Systems "
        "Engineer event is a direct consequence — what does this observation "
        "mean for the system architecture or model? The Developer event is "
        "a further consequence — what needs to be built or changed because of "
        "the SE's response? Be specific: name the observation, the design "
        "impact, and the feature or change needed."
    )
    return prompt


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_single_event_prompt(
    project_description: str,
    discipline: str,
    codebase_context: str | None = None,
    previous_events: str | None = None,
    feedback: str | None = None,
    event_number: int | None = None,
    deliverables_per_event: int = 2,
) -> str:
    guidance = DISCIPLINE_GUIDANCE.get(discipline, "")
    event_label = f"Event {event_number}" if event_number else "an event"
    prompt = (
        f"Generate EXACTLY ONE event — a single event — for {event_label} "
        f"for an intern in the '{discipline}' discipline. ONLY '{discipline}' "
        f"— do not generate events for any other discipline.\n\n"
        f"OUTPUT EXACTLY ONE EVENT. Do NOT generate a second event. "
        f"Do NOT generate Event 2 or any continuation. ONE event only.\n\n"
        f"--- PROJECT README ---\n{project_description}\n--- END README ---\n\n"
        f"Discipline guidance for {discipline}:\n{guidance}\n\n"
        f"Required deliverable count for this event: {deliverables_per_event}. "
        f"Produce exactly {deliverables_per_event} objects in the "
        f"'deliverables' array.\n\n"
        f"{EVENT_FORMAT}"
    )
    prompt = _add_previous_events_context(prompt, previous_events)
    prompt = _add_feedback_context(prompt, feedback)
    if codebase_context:
        prompt += (
            f"\n\nThe following codebase files are available as context. "
            f"Reference them if relevant, but the event does not have to "
            f"involve code.\n\n{codebase_context}"
        )
    prompt += (
        PROMPT_CLOSER +
        " Generate ONLY ONE event in the JSON events array."
    )
    return prompt


def _build_set_prompt(
    project_description: str,
    discipline: str,
    codebase_context: str | None = None,
    previous_events: str | None = None,
    feedback: str | None = None,
    event_number: int = 1,
    deliverables_per_event: int = 2,
) -> str:
    guidance = DISCIPLINE_GUIDANCE.get(discipline, "")
    prompt = (
        f"Generate EXACTLY ONE event for Event {event_number} "
        f"for an intern in the '{discipline}' discipline. "
        f"ONLY '{discipline}' — do not generate events for any other discipline. "
        f"Every event must have **Discipline:** {discipline}.\n\n"
        f"OUTPUT EXACTLY ONE EVENT. Do NOT generate an extra event.\n\n"
        f"--- PROJECT README ---\n{project_description}\n--- END README ---\n\n"
        f"Discipline guidance for {discipline}:\n{guidance}\n\n"
        f"This event must continue the project narrative from prior events. "
        f"It should be a consequence of, or build on, earlier events. "
        f"The project is alive — things happen because of what came before.\n\n"
        f"Required deliverable count per event: {deliverables_per_event}. "
        f"Each event must include exactly {deliverables_per_event} objects in "
        f"'deliverables'.\n\n"
        f"{EVENT_FORMAT}"
    )
    prompt = _add_previous_events_context(prompt, previous_events)
    prompt = _add_feedback_context(prompt, feedback)
    if codebase_context:
        prompt += (
            f"\n\nThe following codebase files are available as context. "
            f"Reference them if relevant to developer events, but not every "
            f"event needs to involve code.\n\n{codebase_context}"
        )
    prompt += (
        PROMPT_CLOSER +
        " Generate ONLY ONE event for this event_number."
    )
    return prompt


def _build_all_disciplines_prompt(
    project_description: str,
    codebase_context: str | None = None,
    previous_events: str | None = None,
    feedback: str | None = None,
    event_number: int = 1,
    cross_reference: bool = False,
    deliverables_per_event: int = 2,
) -> str:
    all_guidance = "\n\n".join(
        f"### {disc}\n{g}" for disc, g in DISCIPLINE_GUIDANCE.items()
    )
    prompt = (
        f"Generate a coordinated set of events for THREE interns "
        f"working on the same project, one in each discipline: "
        f"Business, Systems Engineer, and Developer.\n\n"
        f"--- PROJECT README ---\n{project_description}\n--- END README ---\n\n"
        f"Discipline guidance for each role:\n{all_guidance}\n\n"
        f"Generate events for Event {event_number} only (exactly 3 events total).\n\n"
        f"CAUSAL CHAIN: This event should tell a coherent story across all "
        f"three disciplines. The Business intern observes or discovers something "
        f"in the real world. The Systems Engineer must react to that discovery "
        f"at the architecture/model level. The Developer must build or change "
        f"something because of the SE's response.\n\n"
        f"IMPORTANT — Organize the output by event_number values in JSON.\n"
        f"Use event_number={event_number} for every event this call.\n\n"
        f"STRICT ORDER: Within each event_number, the event order must be exactly: "
        f"Business, then Systems Engineer, then Developer.\n\n"
        f"Required deliverable count per event: {deliverables_per_event}. "
        f"Each event must include exactly {deliverables_per_event} objects in "
        f"'deliverables'.\n\n"
        f"{EVENT_FORMAT}"
    )
    if cross_reference:
        prompt = _add_cross_reference_instruction(prompt)
    prompt = _add_previous_events_context(prompt, previous_events)
    prompt = _add_feedback_context(prompt, feedback)
    if codebase_context:
        prompt += (
            f"\n\nThe following codebase files are available as context. "
            f"Reference them if relevant to developer events, but not every "
            f"event needs to involve code.\n\n{codebase_context}"
        )
    prompt += (
        PROMPT_CLOSER +
        " Generate ONLY Event " + str(event_number) + " with exactly 3 events."
    )
    return prompt


# ---------------------------------------------------------------------------
# File reading helper
# ---------------------------------------------------------------------------

def _read_uploaded_files(uploaded_files) -> str | None:
    """Read uploaded files and return their contents as a formatted string."""
    if not uploaded_files:
        return None

    parts = []
    for f in uploaded_files:
        try:
            content = f.read().decode("utf-8", errors="replace")
            parts.append(f"--- File: {f.name} ---\n{content}\n")
        except Exception:
            parts.append(f"--- File: {f.name} --- (could not read)\n")
    return "\n".join(parts) if parts else None


def _normalize_codebase_context(
    uploaded_files=None,
    codebase_context: str | None = None,
) -> str | None:
    """Use explicit codebase context when provided, otherwise read uploads."""
    if codebase_context is not None:
        return codebase_context
    return _read_uploaded_files(uploaded_files)


# ---------------------------------------------------------------------------
# Main generation entry point
# ---------------------------------------------------------------------------

def generate_events(
    model: str,
    project_description: str,
    mode: str,
    discipline: str | None,
    num_events: int,
    uploaded_files=None,
    previous_events: str | None = None,
    feedback: str | None = None,
    start_event: int = 1,
    cross_reference: bool = False,
    deliverables_per_event: int = 2,
    codebase_context: str | None = None,
):
    """
    Generator that yields streamed text from Ollama.

    Parameters
    ----------
    model : str
        Ollama model name.
    project_description : str
        Project README or description text.
    mode : str
        One of "single", "set", "all".
    discipline : str or None
        Required for "single" and "set" modes.
    num_events : int
        Preserved for compatibility; generation is enforced to one event per call.
    uploaded_files : list or None
        Streamlit uploaded file objects for codebase context.
    previous_events : str or None
        Markdown text of previously generated events for continuity.
    feedback : str or None
        User feedback to steer the generation.
    start_event : int
        Starting event number for generated events.
    cross_reference : bool
        Whether same-event-number events across disciplines should reference each other.
    """
    global LAST_GENERATION_WARNING
    LAST_GENERATION_WARNING = None

    # Enforce single-event generation per invocation.
    num_events = 1
    codebase_context = _normalize_codebase_context(uploaded_files, codebase_context)

    if mode == "single":
        user_prompt = _build_single_event_prompt(
            project_description, discipline, codebase_context,
            previous_events, feedback, start_event, deliverables_per_event,
        )
    elif mode == "set":
        user_prompt = _build_set_prompt(
            project_description, discipline, codebase_context,
            previous_events, feedback, start_event, deliverables_per_event,
        )
    else:
        user_prompt = _build_all_disciplines_prompt(
            project_description, codebase_context,
            previous_events, feedback, start_event, cross_reference,
            deliverables_per_event,
        )

    system_prompt = _build_system_prompt(mode, discipline)
    final_output = ""
    max_attempts = 4
    current_prompt = user_prompt
    previous_artifacts = _collect_prior_artifacts(previous_events)

    for attempt in range(1, max_attempts + 1):
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": current_prompt},
        ]
        stream = ollama.chat(model=model, messages=messages, stream=True)
        candidate = ""
        for chunk in stream:
            token = chunk["message"]["content"]
            if token:
                candidate += token

        events, parse_errors, normalized_json = _parse_events_json(candidate)
        is_valid, errors = _validate_output_shape(
            events=events,
            mode=mode,
            discipline=discipline,
            num_events=num_events,
            start_event=start_event,
            deliverables_per_event=deliverables_per_event,
            previous_artifacts=previous_artifacts,
        )
        errors = parse_errors + errors
        final_output = normalized_json if not parse_errors else candidate
        if is_valid:
            break
        if attempt < max_attempts:
            current_prompt = _build_repair_prompt(user_prompt, candidate, errors)
        else:
            LAST_GENERATION_WARNING = (
                "Output had JSON consistency issues after retries. "
                "Showing best attempt."
            )

    for i in range(0, len(final_output), 120):
        yield final_output[i:i + 120]
