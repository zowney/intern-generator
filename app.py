"""
Intern Simulator — Streamlit application.
Generates realistic weekly events for interns using local Ollama models.
"""

import json

import streamlit as st
from generation_api import request_generate_week, start_local_api_server
from generator import (
    get_available_models,
)

APP_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Intern Simulator",
    layout="centered",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------
DEFAULTS = {
    "event_history": [],       # list of generated markdown strings
    "event_history_json": [],  # list of generated JSON payload strings
    "week_counter": 0,         # tracks how many weeks have been generated
    "last_mode": None,         # remember mode for continue button
    "last_discipline": None,   # remember discipline for continue button
    "last_weeks": 1,           # remember how many weeks the last gen covered
    "pending_action": None,    # "continue_1", "continue_n", "regenerate", or None
    "pending_feedback": None,  # feedback text to use when action fires
    "pending_weeks": 1,        # how many weeks for continue_n
}
for key, val in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = val

# Ensure the local generation API is running for this app process.
start_local_api_server()

# ---------------------------------------------------------------------------
# Minimal custom CSS — solid colors only, no gradients, no emoji
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    .stApp { background-color: #FFFFFF; }
    header[data-testid="stHeader"] { background-color: #FFFFFF; }
    section[data-testid="stSidebar"] { background-color: #F5F5F5; }
    hr { border-color: #BDBDBD; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar — configuration
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Configuration")
    st.caption(f"Version {APP_VERSION}")

    models = get_available_models()
    selected_model = st.selectbox("Ollama Model", options=models, index=0)

    st.divider()

    project_description = st.text_area(
        "Project README / Description",
        height=200,
        placeholder="Paste the project README or a description of the project here...",
    )
    st.caption(
        "Paste a project README or summary. The more detail, the better the events."
    )

    st.divider()

    DISCIPLINES = ["Business", "Systems Engineer", "Developer"]

    mode = st.radio(
        "Generation Mode",
        options=[
            "Single Event",
            "Full Set — One Discipline",
            "Full Set — All Disciplines",
        ],
        index=0,
    )

    # Discipline selector (not needed for "all disciplines" mode)
    discipline = None
    if mode != "Full Set — All Disciplines":
        discipline = st.selectbox("Discipline", options=DISCIPLINES, index=0)

    # Number of weeks (only for set modes)
    num_weeks = 1
    if mode != "Single Event":
        num_weeks = st.number_input(
            "Number of Weeks",
            min_value=1,
            max_value=52,
            value=4,
            step=1,
        )

    deliverables_per_event = st.number_input(
        "Required Deliverables per Event",
        min_value=1,
        max_value=5,
        value=2,
        step=1,
        help="Keep this low for concise outputs.",
    )

    st.divider()

    # Cross-discipline references (only for all-disciplines mode)
    cross_reference = False
    if mode == "Full Set — All Disciplines":
        cross_reference = st.toggle(
            "Cross-discipline references",
            value=True,
            help=(
                "When enabled, events in the same week will explicitly "
                "reference each other across disciplines."
            ),
        )

    st.divider()

    # Codebase upload (optional, mainly for Developer events)
    st.subheader("Codebase Context (optional)")
    st.caption(
        "Upload source files to provide context for developer-oriented events. "
        "Most events do not require this."
    )
    uploaded_files = st.file_uploader(
        "Upload files",
        accept_multiple_files=True,
        label_visibility="collapsed",
    )

    st.divider()

    # History management
    if st.session_state.event_history:
        st.caption(
            f"Timeline: {st.session_state.week_counter} week(s) generated "
            f"across {len(st.session_state.event_history)} generation(s)."
        )
        if st.button("Reset Timeline", use_container_width=True):
            st.session_state.event_history = []
            st.session_state.event_history_json = []
            st.session_state.week_counter = 0
            st.session_state.last_mode = None
            st.session_state.last_discipline = None
            st.session_state.last_weeks = 1
            st.session_state.pending_action = None
            st.session_state.pending_feedback = None
            st.rerun()


# ---------------------------------------------------------------------------
# Helper: run a generation, stream to a container, update state
# ---------------------------------------------------------------------------
def _build_codebase_context(uploaded_file_list) -> str | None:
    """Serialize uploaded files for API requests."""
    if not uploaded_file_list:
        return None

    parts: list[str] = []
    for uploaded in uploaded_file_list:
        try:
            uploaded.seek(0)
            content = uploaded.read().decode("utf-8", errors="replace")
            uploaded.seek(0)
            parts.append(f"--- File: {uploaded.name} ---\n{content}\n")
        except Exception:
            parts.append(f"--- File: {uploaded.name} --- (could not read)\n")
    return "\n".join(parts) if parts else None


def _events_to_markdown(events: list[dict]) -> str:
    """Render structured event JSON to markdown for display."""
    blocks: list[str] = []
    for event in events:
        week = event.get("week", "?")
        title = event.get("title", "Untitled Event")
        discipline = event.get("discipline", "Unknown")
        scenario = (event.get("scenario") or "").strip()
        deliverables = event.get("deliverables") or []

        lines = [
            f"## Week {week}: {title}",
            "",
            f"**Discipline:** {discipline}",
            "",
            "**Scenario:**",
            scenario,
            "",
            "**Required Deliverables:**",
        ]
        for deliverable in deliverables:
            lines.extend(
                [
                    "",
                    f"- **Artifact:** {deliverable.get('artifact', '')}",
                    f"  - **Purpose:** {deliverable.get('purpose', '')}",
                    "  - **Required Contents:** "
                    f"{deliverable.get('required_contents', '')}",
                    f"  - **Audience:** {deliverable.get('audience', '')}",
                    f"  - **Reference:** {deliverable.get('reference', '')}",
                ]
            )
        lines.extend(["", "---"])
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _history_events_payload(history_json: list[str]) -> str | None:
    """Merge prior generation JSON payloads into one previous-events payload."""
    merged_events: list[dict] = []
    for chunk in history_json:
        try:
            parsed = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        events = parsed.get("events")
        if isinstance(events, list):
            merged_events.extend(events)
    if not merged_events:
        return None
    return json.dumps({"events": merged_events}, ensure_ascii=True)


def run_generation(
    container,
    mode_key: str,
    disc: str | None,
    weeks: int,
    start_week: int,
    previous_events_json: str | None,
    feedback_text: str | None = None,
):
    """Generate one week per API call and stream cumulative markdown/JSON."""
    warning_area = container.empty()
    progress_area = container.empty()
    output_area = container.empty()
    warnings: list[str] = []
    week_chunks: list[str] = []
    rolling_events: list[dict] = []
    generated_weeks = 0
    codebase_context = _build_codebase_context(uploaded_files)
    if previous_events_json:
        try:
            parsed = json.loads(previous_events_json)
            prior_events = parsed.get("events")
            if isinstance(prior_events, list):
                rolling_events.extend(prior_events)
        except json.JSONDecodeError:
            pass
    current_previous = (
        json.dumps({"events": rolling_events}, ensure_ascii=True)
        if rolling_events
        else None
    )

    try:
        for offset in range(weeks):
            current_week = start_week + offset
            progress_area.markdown(
                f"Generating week {current_week} "
                f"({offset + 1}/{weeks})..."
            )
            response = request_generate_week(
                {
                    "model": selected_model,
                    "project_description": project_description.strip(),
                    "mode": mode_key,
                    "discipline": disc,
                    "start_week": current_week,
                    "previous_events": current_previous,
                    "feedback": feedback_text,
                    "cross_reference": cross_reference,
                    "deliverables_per_event": int(deliverables_per_event),
                    "codebase_context": codebase_context,
                }
            )
            week_events = response.get("events")
            if not isinstance(week_events, list) or not week_events:
                raise RuntimeError(
                    f"API returned invalid events for week {current_week}."
                )
            week_chunks.append(_events_to_markdown(week_events))
            rolling_events.extend(week_events)
            generated_weeks += 1
            warning_text = response.get("warning")
            if warning_text:
                warnings.append(f"Week {current_week}: {warning_text}")
            current_previous = (
                json.dumps({"events": rolling_events}, ensure_ascii=True)
            )
            output_area.markdown("\n\n".join(week_chunks))
    except Exception as e:
        container.error(f"Generation failed: {e}")
        container.caption(
            "Make sure Ollama is running locally and the selected model is "
            "available. You can pull a model with: ollama pull <model-name>"
        )
        if not week_chunks:
            return None, None, 0
    finally:
        progress_area.empty()

    if warnings:
        warning_area.warning("\n".join(warnings))

    full_response = "\n\n".join(week_chunks)
    full_json = (
        json.dumps({"events": rolling_events}, ensure_ascii=True, indent=2)
        if rolling_events
        else None
    )
    return (full_response if full_response else None), full_json, generated_weeks


# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------
st.title("Intern Simulator")
st.caption(
    "Drop in a project README and generate scenario-driven weekly events for interns."
)

st.divider()

# Show current timeline status
if st.session_state.week_counter > 0:
    st.markdown(
        f"**Project timeline: Week {st.session_state.week_counter} reached** "
        f"-- {len(st.session_state.event_history)} generation(s) in history"
    )
    st.divider()

# ---------------------------------------------------------------------------
# Has history — show timeline + controls
# ---------------------------------------------------------------------------
if st.session_state.event_history:

    # Show past generations (all but the last one collapsed)
    for i, events in enumerate(st.session_state.event_history):
        is_last = i == len(st.session_state.event_history) - 1
        with st.expander(
            f"Generation {i + 1}",
            expanded=is_last,
        ):
            st.markdown(events)

    # --- Streaming area: ABOVE controls, BELOW history ---
    streaming_container = st.container()

    # --- Handle pending actions (generation happens here, above controls) ---
    action = st.session_state.pending_action
    if action is not None:
        fb = st.session_state.pending_feedback
        m = st.session_state.last_mode or "single"
        d = st.session_state.last_discipline

        if action == "regenerate":
            # Remove the last generation and regenerate it
            st.session_state.event_history.pop()
            if st.session_state.event_history_json:
                st.session_state.event_history_json.pop()
            st.session_state.week_counter -= st.session_state.last_weeks
            start_week = st.session_state.week_counter + 1
            weeks = st.session_state.last_weeks
            previous = (
                _history_events_payload(st.session_state.event_history_json)
            )

            with streaming_container:
                st.markdown("**Regenerating with feedback...**")
                result, result_json, generated = run_generation(
                    streaming_container, m, d, weeks, start_week, previous, fb
                )
            if result:
                st.session_state.event_history.append(result)
                if result_json:
                    st.session_state.event_history_json.append(result_json)
                st.session_state.week_counter += generated
                st.session_state.last_weeks = generated
                st.session_state.last_mode = m

        elif action == "continue_1":
            start_week = st.session_state.week_counter + 1
            previous = _history_events_payload(st.session_state.event_history_json)

            with streaming_container:
                st.markdown("**Generating next week...**")
                result, result_json, generated = run_generation(
                    streaming_container, m, d, 1, start_week, previous, fb
                )
            if result:
                st.session_state.event_history.append(result)
                if result_json:
                    st.session_state.event_history_json.append(result_json)
                st.session_state.week_counter += generated
                st.session_state.last_weeks = generated

        elif action == "continue_n":
            weeks = st.session_state.pending_weeks
            start_week = st.session_state.week_counter + 1
            previous = _history_events_payload(st.session_state.event_history_json)
            # Upgrade mode for multi-week if needed
            if m == "single":
                m = "set"

            with streaming_container:
                st.markdown(f"**Generating next {weeks} weeks...**")
                result, result_json, generated = run_generation(
                    streaming_container, m, d, weeks, start_week, previous, fb
                )
            if result:
                st.session_state.event_history.append(result)
                if result_json:
                    st.session_state.event_history_json.append(result_json)
                st.session_state.week_counter += generated
                st.session_state.last_weeks = generated
                st.session_state.last_mode = m

        # Clear the pending action and rerun to show clean state
        st.session_state.pending_action = None
        st.session_state.pending_feedback = None
        st.rerun()

    # --- Controls section (always below streaming area) ---
    st.divider()

    # Download
    all_events = "\n\n".join(st.session_state.event_history)
    st.download_button(
        label="Download Full Timeline",
        data=all_events,
        file_name="intern_events.md",
        mime="text/markdown",
    )
    all_events_json = _history_events_payload(st.session_state.event_history_json)
    st.download_button(
        label="Download Full Timeline JSON",
        data=all_events_json or json.dumps({"events": []}, ensure_ascii=True, indent=2),
        file_name="intern_events.json",
        mime="application/json",
    )

    st.divider()

    # Feedback
    feedback_text = st.text_area(
        "Feedback",
        height=100,
        placeholder=(
            "Steer the next generation or request changes to the last one: "
            "'make events harder', 'focus on compliance', "
            "'the developer should build a dashboard', etc."
        ),
        key="feedback_input",
    )

    # Action buttons
    col_regen, col_next, col_extend = st.columns([1, 1, 1])

    with col_regen:
        has_feedback = bool(feedback_text and feedback_text.strip())
        if st.button(
            "Regenerate Last",
            use_container_width=True,
            disabled=not has_feedback,
            help="Provide feedback above, then regenerate the most recent generation.",
        ):
            st.session_state.pending_action = "regenerate"
            st.session_state.pending_feedback = feedback_text
            st.rerun()

    with col_next:
        if st.button("Next Week", use_container_width=True):
            st.session_state.pending_action = "continue_1"
            st.session_state.pending_feedback = feedback_text
            st.rerun()

    with col_extend:
        extend_weeks = st.number_input(
            "Weeks",
            min_value=1,
            max_value=52,
            value=4,
            step=1,
            key="extend_weeks",
            label_visibility="collapsed",
        )
        if st.button(
            f"Next {extend_weeks} Weeks",
            use_container_width=True,
        ):
            st.session_state.pending_action = "continue_n"
            st.session_state.pending_feedback = feedback_text
            st.session_state.pending_weeks = extend_weeks
            st.rerun()

# ---------------------------------------------------------------------------
# No history — initial generation
# ---------------------------------------------------------------------------
else:
    can_generate = bool(project_description and project_description.strip())

    if not can_generate:
        st.info(
            "Paste a project README or description in the sidebar to get started."
        )

    generate_clicked = st.button(
        "Generate Events",
        disabled=not can_generate,
        use_container_width=True,
    )

    if generate_clicked and can_generate:
        # Determine internal mode key
        if mode == "Single Event":
            mode_key = "single"
        elif mode.startswith("Full Set") and "One" in mode:
            mode_key = "set"
        else:
            mode_key = "all"

        container = st.container()
        result, result_json, generated = run_generation(
            container, mode_key, discipline, num_weeks, 1, None
        )
        if result:
            st.session_state.event_history.append(result)
            if result_json:
                st.session_state.event_history_json.append(result_json)
            st.session_state.week_counter += generated
            st.session_state.last_mode = mode_key
            st.session_state.last_discipline = discipline
            st.session_state.last_weeks = generated
            st.rerun()
