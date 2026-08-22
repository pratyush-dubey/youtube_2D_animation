# AI Video Director architecture

The default product workflow is intentionally small:

1. Open `http://127.0.0.1:8000/`.
2. Describe the finished video, choose duration/language/style, and select **Create Video**.
3. The API immediately returns a `project_id` and `job_id`; production continues in a background thread.
4. The project page polls one high-level state document and displays the production timeline.
5. A video can be approved only after the graph completes and its quality score meets `MINIMUM_VIDEO_QUALITY_SCORE`.

`app/director/director.py` owns the production graph, dependency validation,
specialized directors, retries, targeted QA repair, safe user messages, and the
final human gate. Existing agents remain internal workers. Their editors and
diagnostics are available through Advanced Mode, but are not part of normal use.

The first supported production target is 60 seconds. The graph accepts longer
durations already, but 5, 10, and 20 minute reliability should be validated in
that order after the 60-second local stack succeeds.

## Local-first operation

Run `start_video_generator.bat`. It checks or starts Ollama and ComfyUI, starts
the FastAPI application (which also serves the frontend), waits for health, and
opens the Director page. FFmpeg, Blender, local TTS, and image-generation
providers remain internal workers. Gemini is optional; paid APIs are not
required by the architecture.

For a real production test, use `LLM_PROVIDER=ollama`, a local ComfyUI-backed
image provider, and a working local Piper model. `placeholder` imagery is useful
for wiring tests but is intentionally not expected to pass the 85/100 final
quality gate.

## States

`QUEUED -> PRODUCING -> VIDEO_READY -> APPROVED`

Stage exhaustion results in `REQUIRES_ATTENTION`. A quality score below the
configured threshold triggers targeted repair attempts and then
`EDITOR_REVIEW`; publishing remains blocked in both states.
