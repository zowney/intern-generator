"""
Groq-based event generator for the intern simulator.
Handles prompt construction and model interaction via the Groq cloud API.
"""

import re

import streamlit as st
from groq import Groq

# ---------------------------------------------------------------------------
# Groq client (uses API key from Streamlit secrets or env var)
# ---------------------------------------------------------------------------

def _get_client() -> Groq:
    """Return a Groq client using the API key from Streamlit secrets."""
    api_key = st.secrets.get("GROQ_API_KEY", None)
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY not found. Add it to .streamlit/secrets.toml "
            "or set it as an environment variable."
        )
    return Groq(api_key=api_key)


# Available models on Groq's free tier (open-source)
GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]


def get_available_models() -> list[str]:
    """Return the list of Groq-hosted open-source models."""
    return GROQ_MODELS


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
# Output format template
# ---------------------------------------------------------------------------

EVENT_FORMAT = (
    "Format each event using this structure:\n\n"
    "## Week N: [Short, descriptive title]\n\n"
    "**Discipline:** [Business / Systems Engineer / Developer]\n\n"
    "**Scenario:**\n"
    "[Describe what happened or what situation has arisen. Write this as if "
    "the intern is being briefed about something that just occurred — an "
    "observation, a discovery, a change, a problem, or an opportunity. "
    "Be SPECIFIC: use concrete details, numbers, names of systems, real-world "
    "references grounded in the project context. Do NOT tell the intern what "
    "to do or how to solve it. Present the situation and let them figure out "
    "the response. One to three paragraphs.]\n\n"
    "**Required Deliverables:**\n"
    "- [Deliverable name] — [artifact type such as MBSE model update, "
    "Word/Google doc brief, slide deck, diagram, spreadsheet, etc.]\n"
    "- [Deliverables must state WHAT is submitted, not HOW to produce it]\n\n"
    "---\n\n"
    "Rules:\n"
    "- Do NOT include tasks, steps, solutions, or hints.\n"
    "- The scenario should read like a real event that triggers action.\n"
    "- Deliverables describe WHAT is needed, not HOW to do it.\n"
    "- Separate events with a horizontal rule (---).\n"
    "- Do not use emojis. Use plain, professional language."
)

# Appended to the very end of every user prompt to force compliance
PROMPT_CLOSER = (
    "\n\nIMPORTANT: Do NOT ask any questions. Do NOT add any introduction, "
    "commentary, or explanation. You have everything you need above. "
    "Begin your response IMMEDIATELY with '## Week' and generate the events. "
    "Your very first characters must be '## Week'."
)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def _build_system_prompt(mode: str, discipline: str | None = None) -> str:
    base = (
        "You are a project simulation engine. You ONLY output event content "
        "in markdown format. You NEVER ask questions. You NEVER add commentary, "
        "introductions, or explanations. You NEVER say things like 'Let me know' "
        "or 'What kind of project'. You have all the information you need in the "
        "user message.\n\n"
        "Your SOLE job: read the project description provided and immediately "
        "output events in the exact markdown format specified. Start your "
        "response with '## Week' — nothing before it.\n\n"
        "You simulate a living, evolving project by generating weekly events — "
        "things that HAPPEN — that interns must respond to. You are NOT "
        "generating task lists. You are generating realistic scenarios.\n\n"
        "WORLD-BUILDING: You MUST invent specific, concrete, fictional details "
        "for every event. Make up dates, locations, organization names, vessel "
        "names, report titles, personnel names, measurements, and sources. "
        "The events should feel like real intelligence reports or project "
        "dispatches — not vague summaries. The more specific and grounded "
        "the details, the better the simulation.\n\n"
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
        "- Each event = one week of work.\n"
        "- Present the SITUATION with specific, concrete details.\n"
        "- Do not tell the intern what to do — describe what happened.\n"
        "- Events should be realistic and appropriately scoped for an intern.\n"
        "- Later events must build on consequences of earlier ones.\n"
        "- Do not use emojis anywhere.\n"
        "- Use plain, professional language.\n"
        "- NEVER include preamble, questions, or commentary.\n"
        "- Your first line of output MUST be '## Week'.\n"
        "- Every event MUST include a '**Discipline:**' line.\n"
        "- Week headers must use integer numbering only (Week 1, Week 2, ...).\n"
    )

    return base


def get_last_generation_warning() -> str | None:
    """Return warning text from last generation attempt, if any."""
    return LAST_GENERATION_WARNING


def _split_week_blocks(text: str) -> list[tuple[int, str]]:
    """
    Split output into week blocks.
    Returns list of (week_number, block_text).
    """
    pattern = re.compile(r"(?m)^##\s*Week\s+(\d+)[^\n]*\n")
    matches = list(pattern.finditer(text))
    blocks: list[tuple[int, str]] = []
    for i, match in enumerate(matches):
        week_number = int(match.group(1))
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks.append((week_number, text[start:end].strip()))
    return blocks


def _extract_discipline(block_text: str) -> str | None:
    match = re.search(
        r"(?im)^\*\*Discipline:\*\*\s*(Business|Systems Engineer|Developer)\s*$",
        block_text,
    )
    return match.group(1) if match else None


def _validate_output_shape(
    text: str,
    mode: str,
    discipline: str | None,
    num_weeks: int,
    start_week: int,
) -> tuple[bool, list[str]]:
    """
    Validate generated output for week continuity and discipline consistency.
    """
    errors: list[str] = []
    blocks = _split_week_blocks(text)
    if not blocks:
        return False, ["No valid '## Week N' sections were found."]

    expected_weeks = list(range(start_week, start_week + num_weeks))

    if mode in {"single", "set"}:
        if len(blocks) != num_weeks:
            errors.append(
                f"Expected {num_weeks} week section(s), found {len(blocks)}."
            )

        got_weeks = [week for week, _ in blocks]
        if got_weeks != expected_weeks:
            errors.append(
                f"Week numbering mismatch. Expected {expected_weeks}, got {got_weeks}."
            )

        if discipline:
            for idx, (_, block) in enumerate(blocks, start=1):
                block_discipline = _extract_discipline(block)
                if block_discipline != discipline:
                    errors.append(
                        f"Week block {idx} has discipline '{block_discipline}', "
                        f"expected '{discipline}'."
                    )

    else:
        expected_count = num_weeks * 3
        if len(blocks) != expected_count:
            errors.append(
                f"Expected {expected_count} sections for all-disciplines mode, "
                f"found {len(blocks)}."
            )

        week_counts: dict[int, int] = {}
        week_to_disciplines: dict[int, set[str]] = {}
        week_discipline_order: dict[int, list[str]] = {}
        for week, block in blocks:
            week_counts[week] = week_counts.get(week, 0) + 1
            disc = _extract_discipline(block)
            if disc:
                week_to_disciplines.setdefault(week, set()).add(disc)
                week_discipline_order.setdefault(week, []).append(disc)

        for week in expected_weeks:
            if week_counts.get(week, 0) != 3:
                errors.append(
                    f"Week {week} should appear 3 times, found "
                    f"{week_counts.get(week, 0)}."
                )
            found = week_to_disciplines.get(week, set())
            if found != set(DISCIPLINE_ORDER):
                errors.append(
                    f"Week {week} discipline set mismatch. "
                    f"Expected {DISCIPLINE_ORDER}, got {sorted(found)}."
                )
            order = week_discipline_order.get(week, [])
            if order != DISCIPLINE_ORDER:
                errors.append(
                    f"Week {week} discipline order mismatch. "
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
        "Your previous answer violated formatting or consistency constraints.\n\n"
        "You MUST rewrite the full answer from scratch using the original task.\n"
        "Do not explain. Do not apologize. Output only corrected events.\n\n"
        "--- ORIGINAL TASK ---\n"
        f"{original_prompt}\n"
        "--- END ORIGINAL TASK ---\n\n"
        "--- VALIDATION ERRORS TO FIX ---\n"
        f"{joined_errors}\n"
        "--- END VALIDATION ERRORS ---\n\n"
        "--- INVALID OUTPUT (FOR REFERENCE) ---\n"
        f"{invalid_output}\n"
        "--- END INVALID OUTPUT ---\n\n"
        "Now provide only the corrected markdown events."
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
            "Advance the project timeline forward.\n\n"
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
    """Add instruction for same-week events to reference each other."""
    prompt += (
        "\n\nCROSS-DISCIPLINE REFERENCES: Events in the same week MUST "
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
    week_number: int | None = None,
    deliverables_per_event: int = 2,
) -> str:
    guidance = DISCIPLINE_GUIDANCE.get(discipline, "")
    week_label = f"Week {week_number}" if week_number else "a week"
    prompt = (
        f"Generate EXACTLY ONE event — a single event — for {week_label} "
        f"for an intern in the '{discipline}' discipline. ONLY '{discipline}' "
        f"— do not generate events for any other discipline.\n\n"
        f"OUTPUT EXACTLY ONE EVENT. Do NOT generate a second event. "
        f"Do NOT generate Week 2 or any continuation. ONE event only. "
        f"Stop after the first horizontal rule (---).\n\n"
        f"--- PROJECT README ---\n{project_description}\n--- END README ---\n\n"
        f"Discipline guidance for {discipline}:\n{guidance}\n\n"
        f"Required deliverable count for this event: {deliverables_per_event}. "
        f"Produce exactly {deliverables_per_event} bullet item(s) under "
        f"'**Required Deliverables:**'.\n\n"
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
        " Generate ONLY ONE event. Stop after the --- separator."
    )
    return prompt


def _build_set_prompt(
    project_description: str,
    discipline: str,
    num_weeks: int,
    codebase_context: str | None = None,
    previous_events: str | None = None,
    feedback: str | None = None,
    start_week: int = 1,
    deliverables_per_event: int = 2,
) -> str:
    guidance = DISCIPLINE_GUIDANCE.get(discipline, "")
    end_week = start_week + num_weeks - 1
    prompt = (
        f"Generate a set of {num_weeks} weekly events (Week {start_week} through "
        f"Week {end_week}) for an intern in the '{discipline}' discipline. "
        f"ONLY '{discipline}' — do not generate events for any other discipline. "
        f"Every event must have **Discipline:** {discipline}.\n\n"
        f"--- PROJECT README ---\n{project_description}\n--- END README ---\n\n"
        f"Discipline guidance for {discipline}:\n{guidance}\n\n"
        f"The events must form a continuous narrative over {num_weeks} weeks. "
        f"Later events should be consequences of, or build on, earlier ones. "
        f"The project is alive — things happen because of what came before.\n\n"
        f"Required deliverable count per event: {deliverables_per_event}. "
        f"Each event must include exactly {deliverables_per_event} bullet "
        f"item(s) under '**Required Deliverables:**'.\n\n"
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
    prompt += PROMPT_CLOSER
    return prompt


def _build_all_disciplines_prompt(
    project_description: str,
    num_weeks: int,
    codebase_context: str | None = None,
    previous_events: str | None = None,
    feedback: str | None = None,
    start_week: int = 1,
    cross_reference: bool = False,
    deliverables_per_event: int = 2,
) -> str:
    all_guidance = "\n\n".join(
        f"### {disc}\n{g}" for disc, g in DISCIPLINE_GUIDANCE.items()
    )
    end_week = start_week + num_weeks - 1
    prompt = (
        f"Generate a coordinated set of weekly events for THREE interns "
        f"working on the same project, one in each discipline: "
        f"Business, Systems Engineer, and Developer.\n\n"
        f"--- PROJECT README ---\n{project_description}\n--- END README ---\n\n"
        f"Discipline guidance for each role:\n{all_guidance}\n\n"
        f"Generate events for Week {start_week} through Week {end_week} "
        f"({num_weeks * 3} events total).\n\n"
        f"CAUSAL CHAIN: Each week should tell a coherent story across all "
        f"three disciplines. The Business intern observes or discovers something "
        f"in the real world. The Systems Engineer must react to that discovery "
        f"at the architecture/model level. The Developer must build or change "
        f"something because of the SE's response. Later weeks build on the "
        f"consequences of earlier weeks.\n\n"
        f"IMPORTANT — Organize the output BY WEEK, not by discipline:\n"
        f"# Week N\n"
        f"Show the Business event, then Systems Engineer event, then Developer "
        f"event for that week. Then move to the next week.\n\n"
        f"STRICT ORDER: Within each week, the event order must be exactly: "
        f"Business, then Systems Engineer, then Developer.\n\n"
        f"Required deliverable count per event: {deliverables_per_event}. "
        f"Each event must include exactly {deliverables_per_event} bullet "
        f"item(s) under '**Required Deliverables:**'.\n\n"
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
    prompt += PROMPT_CLOSER
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


# ---------------------------------------------------------------------------
# Main generation entry point
# ---------------------------------------------------------------------------

def generate_events(
    model: str,
    project_description: str,
    mode: str,
    discipline: str | None,
    num_weeks: int,
    uploaded_files=None,
    previous_events: str | None = None,
    feedback: str | None = None,
    start_week: int = 1,
    cross_reference: bool = False,
    deliverables_per_event: int = 2,
):
    """
    Generator that yields streamed text from Groq.

    Parameters
    ----------
    model : str
        Groq model name (e.g. 'llama-3.3-70b-versatile').
    project_description : str
        Project README or description text.
    mode : str
        One of "single", "set", "all".
    discipline : str or None
        Required for "single" and "set" modes.
    num_weeks : int
        Number of weeks (events) to generate.
    uploaded_files : list or None
        Streamlit uploaded file objects for codebase context.
    previous_events : str or None
        Markdown text of previously generated events for continuity.
    feedback : str or None
        User feedback to steer the generation.
    start_week : int
        Starting week number for generated events.
    cross_reference : bool
        Whether same-week events across disciplines should reference each other.
    """
    global LAST_GENERATION_WARNING
    LAST_GENERATION_WARNING = None

    codebase_context = _read_uploaded_files(uploaded_files)

    if mode == "single":
        user_prompt = _build_single_event_prompt(
            project_description, discipline, codebase_context,
            previous_events, feedback, start_week, deliverables_per_event,
        )
    elif mode == "set":
        user_prompt = _build_set_prompt(
            project_description, discipline, num_weeks, codebase_context,
            previous_events, feedback, start_week, deliverables_per_event,
        )
    else:
        user_prompt = _build_all_disciplines_prompt(
            project_description, num_weeks, codebase_context,
            previous_events, feedback, start_week, cross_reference,
            deliverables_per_event,
        )

    system_prompt = _build_system_prompt(mode, discipline)
    final_output = ""
    max_attempts = 3
    current_prompt = user_prompt
    client = _get_client()

    for attempt in range(1, max_attempts + 1):
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": current_prompt},
        ]
        stream = client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
        )
        candidate = ""
        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                candidate += delta.content

        is_valid, errors = _validate_output_shape(
            text=candidate,
            mode=mode,
            discipline=discipline,
            num_weeks=num_weeks,
            start_week=start_week,
        )
        final_output = candidate
        if is_valid:
            break
        if attempt < max_attempts:
            current_prompt = _build_repair_prompt(user_prompt, candidate, errors)
        else:
            LAST_GENERATION_WARNING = (
                "Output had formatting consistency issues after retries. "
                "Showing best attempt."
            )

    for i in range(0, len(final_output), 120):
        yield final_output[i:i + 120]




