# AGENTS

## Project Snapshot

Intern Simulator is a Streamlit application that generates scenario-driven weekly events for internship training in defense-adjacent project contexts.

There are two nearly parallel deployments:
- Root app uses local Ollama (`app.py`, `generator.py`)
- `groq-deploy` app uses Groq API (`groq-deploy/app.py`, `groq-deploy/generator.py`)

Both variants should remain behaviorally aligned.

## Primary Workflow

1. User selects model, mode, discipline, and deliverable count.
2. User provides project description and optional uploaded code files.
3. Generator builds prompt(s), calls model, validates output, retries repair up to 3 times.
4. UI displays output, warning state (if needed), and timeline history controls.

## Output Requirements

Every event must include:
- Week header (`## Week N`)
- Discipline line
- Scenario section
- Required Deliverables section

Every deliverable must include these labels:
- `Artifact`
- `Purpose`
- `Required Contents`
- `Audience`
- `Reference`

`Reference` should include both:
- A specific defense document/review reference (examples: CDRL, DID, CONOPS, ICD, SRD, TEMP, PDR, CDR)
- A generic contract-style artifact reference (examples: briefing, memo, report, analysis)

## Validation and Repair

Validator enforces:
- Correct week continuity
- Discipline consistency for single/set modes
- All-discipline completeness and strict weekly order:
  - Business -> Systems Engineer -> Developer
- Exact configured deliverable count per event
- Deliverable field and reference requirements

If validation fails, generator sends a repair prompt and retries.
If still invalid after 3 attempts, it returns best effort and sets warning text consumed by the UI.

Generation is week-by-week only across all modes; multi-week batch generation is intentionally disabled.

## Design and Tech Constraints

- UI: Streamlit only
- Visual style: no emojis, no gradients, restrained neutral palette
- Local AI path: Ollama
- Cloud AI path: Groq
- Keep dependencies minimal per existing requirements files

## Change Guidance

- Keep root and `groq-deploy` behavior synchronized unless divergence is intentional.
- Prefer lightweight, transient in-memory logic over persistent storage for generation quality controls.
- Preserve deterministic output contract checks in validators when editing prompt formats.
