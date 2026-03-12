# Intern Simulator

Streamlit app for generating realistic weekly internship events from a project description.

The project supports two run modes:
- Local open-source inference with Ollama (`app.py`, `generator.py`)
- Cloud-hosted open-source inference with Groq (`groq-deploy/app.py`, `groq-deploy/generator.py`)

## Core Behavior

- Generates events for three disciplines: Business, Systems Engineer, Developer
- Supports:
  - Single event
  - One-week generation for one discipline
  - One-week generation for all disciplines
- Multi-week actions are orchestrated as repeated one-week API calls (`/generate-week`)
- Maintains timeline history in session state
- Supports regeneration, continuation, and download of the full timeline
- Generates one week at a time only (no multi-week batch generation)

## Output Contract

Each event is required to follow:
- `## Week N: ...`
- `**Discipline:** ...`
- `**Scenario:** ...`
- `**Required Deliverables:** ...`

Each deliverable entry is structured with:
- `Artifact`
- `Purpose`
- `Required Contents`
- `Audience`
- `Reference`

The `Reference` field must include:
- A specific defense artifact/review reference (for example CDRL, DID, CONOPS, ICD, SRD, TEMP, PDR, CDR)
- A generic contract-style artifact reference (for example briefing, memo, report, analysis)

Deliverable count is configurable in the sidebar (`Required Deliverables per Event`).

## Reliability Guardrails

Generation uses a validate-and-repair loop (up to 3 attempts) to enforce:
- Week numbering continuity
- Discipline consistency for single/set modes
- Exact per-week ordering in all-discipline mode:
  - Business -> Systems Engineer -> Developer
- Required deliverable count per event
- Required deliverable field presence and document reference constraints

If retries are exhausted, the app returns the best attempt and shows a warning above the output.

## Run Locally (Ollama)

```bash
cd /home/rowanm/Documents/Work/Arcfield/intern-generator
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
ollama pull llama3.2
streamlit run app.py
```

## Run Groq Variant

```bash
cd /home/rowanm/Documents/Work/Arcfield/intern-generator/groq-deploy
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
mkdir -p .streamlit
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# add GROQ_API_KEY in .streamlit/secrets.toml
streamlit run app.py
```
