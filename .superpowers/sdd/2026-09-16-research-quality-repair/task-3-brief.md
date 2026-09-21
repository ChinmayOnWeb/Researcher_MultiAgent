### Task 3: Add v3 events, replay, and safe storage

**Files:** create `research/events.py`, `research/store.py`, `tests/unit/test_research_events.py`, `tests/unit/test_research_store.py`.

**Consumes:** Sections 6 and Task 2 contracts; existing locking and file primitives. **Produces:** ResearchSnapshot, ResearchEvent, `initialize_research(request_path,run_dir)`, `open_research_run(run_dir)`, `load_research_status(run_dir)`, locked append/write_capture/materialize operations.

Locked store methods: `append(event)->ResearchSnapshot`; `write_capture(action_id,name,data)->sha256`; `snapshot` and immutable `events`. Canonical capture names only stdout.bin/stderr.log. `initialize_research` parses the entire request before creating a destination, follows legacy empty/lock-only destination rules, and snapshots inline sources in initialization-derived projections.

- [ ] Write hand-authored event fixtures for Quick complete and Deep including one repair; do not generate fixtures through engine under test.
- [ ] Assert contiguous chronology, duplicate initialization, unknown events, finish without intent, altered packet hash, finish for wrong action, action after terminal, gate duplicate/conflict all fail.
- [ ] Implement strict store layout and event replay. Check every existing directory even if a different expected projection is missing. Verify capture digests before repair.
- [ ] Add recovery fault injection at decision commit, intent projection, first/second capture, action finish commit, gate response commit, and final report materialization.

```python
def test_finished_result_survives_projection_failure(self):
    run = make_run_through_intent()
    publish_captures(run)
    with fail_result_projection_once():
        with self.assertRaises(RunStoreError):
            commit_finished_result(run)
    recovered = load_research_status(run)
    self.assertIn("a0001", recovered.results)

def test_corrupt_capture_prevents_every_repair(self):
    run = make_run_through_finish()
    tamper_capture(run, "a0001", b"different")
    remove_state_projection(run)
    with self.assertRaises(RunCorruptError):
        load_research_status(run)
    self.assertFalse((run / "state.json").exists())
```

- [ ] Test links/reparse/hardlinks, unknown root report, oversized event, stale temp aliases, unsafe action IDs. Capture a complete v2 fixture's bytes before/after legacy status and assert unchanged.
- [ ] Run `py -m unittest tests.unit.test_research_events tests.unit.test_research_store tests.unit.test_run_store -v`. Commit. Astra reviews storage imports and immutable publication before dependent tasks.

