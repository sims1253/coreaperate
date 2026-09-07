# Test evidence, 2026-09-07

## Actually executed

- Windows 11 build 26200, Python 3.13.13, websockets 17.0.1, pytest 8.4.2, Lupa 2.6.
- The installed websockets `serve` and `connect` signatures were inspected. Code uses `websockets.asyncio`, single-argument server handlers, explicit message limits, `compression=None`, and `proxy=None` on clients.
- REAPER **7.79/x64** was installed. A separate configuration and empty disposable projects under `runtime/` were used. No real user project or Syncthing configuration was edited.
- **Real REAPER capability probe: SUCCESS.** Note insert/readback, QN conversion, persistent item/take/project extension-state calls, raw event round trip, hidden-note retention on right trim, and same-directory Lua file rename. Raw marker observed: tick 3840, flags 0, bytes `b0 7b 00`.
- **Real REAPER adapter smoke: 11 checks passed, SUCCESS.** Unicode track names, shared pan, hidden notes, note mute/channel, item move/create/delete, note-selection-only exclusion, unchanged selection preservation, cursor preservation, CC rejection without removal, and complete supported-model round trip.
- The smoke run predates final guard/limit and recovery-panel hardening. All final Lua files compile in the automated suite; the final full bridge still requires the manual REAPER run.
- Official REAPER 7.79 reference checked for every API call currently used: 72 Lua signatures extracted, zero missing. `api-signatures.txt` records them. An installed REAPER-generated HTML reference was not available in the installed Docs folder, so the matching-version official web reference was used plus actual probes. Gfx/defer usage follows the official built-in reference.
- **Manual two-instance trial:** basic MIDI synchronization, separate track claims, unauthorized-track divergence, and explicit restoration to accepted state were confirmed by the tester. This was an exploratory trial, not completion of the full acceptance checklist.

## Follow-up: pan-mode startup rejection

The first user panel run paused at `model.lua` pan validation. Recovery exports showed demo tracks without an explicit pan-mode override. A capture-level regression reproduced the same rejection when `I_PANMODE` was inherited (-1), despite an effective balance mode. The bridge now validates `GetTrackUIPan`'s resolved mode, retaining rejection of effective stereo/dual pan. Seven regression cases cover inherited/explicit supported and unsupported modes; the full suite passes 21 tests. These regression cases mock API return values and do not constitute a new real-REAPER pass. The running panels must be restarted to load the fix; their message queues accumulated during the original pause, so Connect may be needed again after the backlog drains.

## Automated suite

Run `.\.venv\Scripts\python -m pytest -q`. Tests cover:

- Independent per-track concurrent edits through real WebSockets; equal delivery sequence.
- Ownership contention/permissions, stale epochs/revisions, handover.
- SQLite restart, accepted/rejected operation dedup, ID-content conflicts, history replay, scoped undo and stale inverse refusal.
- Identity collisions, hidden notes, malformed JSON/numeric ranges, and bounded IPC.
- Pure Lua canonical serialization/diff/state-machine behavior, newer pending work during self-echo, unowned divergence, sequence gaps, and apply-failure non-advancement.
- **Actual Lua ↔ Python files**, acknowledgements, Unicode/empty containers, and interrupted `.tmp` writes on Windows.
- Two real companion loops plus WebSockets/SQLite/disk spool, and refusal to publish an old unaccepted offline proposal. The musical endpoint in this test is simulated; it is **not** a REAPER end-to-end test.

The initial public commit passes **21 automated tests**. Raw console logs, machine evidence, working projects, IPC state, and recovery exports are kept out of version control. Static schema is descriptive; the actual strict Python semantic validators enforce additional UTF-8 byte, sorting, identity, and whole-project limits.

## Unverified / partial

Beyond the basic manual trial, native simultaneous editing under load, native Undo paths, tab switching while actively receiving, save/close/reopen identity behavior, and all gfx controls have not been systematically validated as an integrated system. No true edit latency or audible playback disruption measurement was made. ReaSynth instantiated successfully, but audio equivalence was not evaluated.

macOS and Linux, their rename/locking behavior, non-default MIDI source resolutions across peers, process crashes during a real REAPER apply, and machine power loss are unverified. A project-size cap bounds input size but is not a measured callback-time guarantee. Changed/ambiguous note selection behavior remains a limitation.

Next smallest milestone: run `MANUAL_TEST.md` with two disposable REAPER instances, fix any integration failures, and record canonical equality and actual timing/playback observations before using this for real collaboration.

## References

- [Official REAPER ReaScript overview](https://www.reaper.fm/sdk/reascript/reascript.php)
- [Official REAPER 7.79 API reference](https://www.reaper.fm/sdk/reascript/reascripthelp.html)
- [websockets 17.0.1 asyncio server reference](https://websockets.readthedocs.io/en/17.0.1/reference/asyncio/server.html)
- [dkjson vendored upstream source](https://github.com/LuaDist/dkjson/blob/master/dkjson.lua), version 2.5; license embedded and copied into `licenses/`.
