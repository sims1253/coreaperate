# Protocol and recovery contract

Protocol 1 is JSON over a bounded WebSocket connection, with a file spool on each REAPER host. The executable validators are `coreaperate/model.py` and `store.py`; `schema/protocol.schema.json` describes proposals. JSON decoding rejects duplicate keys, invalid JSON, nonfinite numbers, and messages over 1 MiB. WebSocket framing is also limited to 1 MiB. Coordinator payload validation occurs before state mutation.

## Canonical model

The project object has exactly `session`, `config`, `order`, and `tracks`. Config has integer `tempo` in micro-BPM, `numerator`, and `denominator`. Track order is an array of stable IDs. Tracks are objects keyed by stable ID and contain `id`, Unicode `name` (512 UTF-8 bytes maximum), integer `volume` (linear gain × 1,000,000), integer `pan` (−1,000,000…1,000,000), and an `items` object.

Items have `id`, `take`, `position`, `length`, and `notes`. Position/length and note onset/duration use integer **millionths of a quarter note**. Item position is absolute project QN; note onset is relative to item position. Duration stays independent of the visible right edge. Notes are lexicographically sorted seven-element arrays:

```text
[onset, duration, pitch, velocity, zero-based channel, musical mute 0/1, reserved 0]
```

Onsets are nonnegative, duration positive, pitch 0–127, velocity 1–127, channel 0–15. Duplicate identical notes remain duplicate array entries. Objects use exact key/value equality; note arrays use exact integer equality. Lua quantizes with `floor(x * 1e6 + 0.5)`. Python canonical serialization sorts keys, uses compact separators, emits Unicode UTF-8 without ASCII escaping, and prohibits NaN. The baseline digest is SHA-256 of that Python serialization. Lua sends its decoded baseline to Python, so object key iteration order cannot change the digest. Raw MIDI PPQ values never cross the network; stock PPQ/project-QN conversion APIs handle each source's resolution. Rounding finer than a native source tick is still subject to REAPER's own tick quantization; apply/readback mismatch pauses safely.

Transport, cursors, selection bits, note editor state, track/item audition mute, solo, record arm, monitoring, and master settings are not fields in this model. Unknown MIDI is conservatively rejected before note replacement. A final unselected/unmuted channel-1 CC123 with value zero, at the verified source QN end, is source bookkeeping; empty delta spacer records are also bookkeeping. User CC/text/SysEx records elsewhere are rejected and preserved. Orphan events, extra event flags, and nonzero note-off velocity are rejected.

## Identity

Session and the prepared/accepted JSON models use `SetProjExtState`/`GetProjExtState`. Track IDs are native `GetTrackGUID` values, retained by baseline copies. Items/takes use `P_EXT:coreaperate_id`; items additionally store `P_EXT:coreaperate_birth`, the native item GUID at assignment. A copied item with a changed native GUID gets new item/take IDs only if its original is still present. Otherwise identity is ambiguous and the bridge pauses. Duplicate IDs and shared MIDI source pool GUIDs pause. IDs are never derived from track numbers, item indexes, selection, or pointers; indexes are used only to enumerate and establish pointer maps for the bound project.

SQLite retains an identity registry beyond item deletion, preventing an ID from being reused for a different item or track. Ownership is attached to track ID. Participant identity/token and IPC project-path binding are local files, not copied project metadata.

## Connection and operations

First message: `{type:"hello", protocol:1, client, token, session, baseline}`. Actor is derived from the validated credential. Exactly two credential entries are accepted; duplicate simultaneous connections for one identity are rejected. The server sends a snapshot and peer presence. Host participation uses this same handshake.

Every proposal has exactly `protocol`, `session`, `id`, `track`, `revision`, `epoch`, `type`, and `payload`. Types: `claim`, `release`, `handover`, `properties`, `put_item`, `delete_item`, `undo`. Properties carry all three shared track controls; put_item replaces one canonical item/take; delete_item carries an item ID. Control payloads are empty except handover's `owner`. There are no arbitrary command or path fields.

The server validates current track ownership, revision, epoch, schema/ranges, and whole-model identities. A transaction stores the resulting state, operation fingerprint and outcome, history before/after, and identities before acknowledgement. Reused operation IDs return the original outcome (accepted **or rejected**), including across restart. Changed contents or actor under the same ID are rejected. Structurally undecodable messages are connection errors and do not get operation records.

Revision changes affect only the target track. The session sequence orders all accepted events. Coordinator restart increments every ownership epoch while retaining reservations. This fences queued messages from the old coordinator lifetime. Broadcast delivery is serialized. Replay retains all history; acknowledgements do not prune it.

`replay` requests history after a sequence. `snapshot_request` requests current state. `outcome_request` queries an existing operation without publishing it. `ack` is a bridge-applied sequence watermark. A received snapshot must still pass live-data checks; it is never blanket overwrite permission.

## Bridge state machine

`reaper/lib/engine.lua` has no REAPER API calls except GUID generation for proposals. It tracks accepted state, per-track in-flight operations, metadata, and sequence. The panel separately records last observed local state and settling time. One operation per track may be in flight. Further native changes remain in the live project and are coalesced into the next diff after acknowledgement.

Self-echo accepts the authoritative baseline without writing it into live state, preserving newer pending edits. Remote events check live state against accepted state immediately before application. The adapter captures again before applying and again afterward. Errors do not advance accepted state or send application acknowledgement. Pre-apply exports preserve live chunks for recovery. The panel pauses the whole client on divergence rather than risking other scopes.

Clean restart matches live state to accepted checkpoint or current snapshot. Unsent/offline differences cause recovery. Old proposals in the spool are outcome queries after reconnect; unknown ones become rejected branch work. Fresh proposals wait until the bridge signals `ready` after snapshot reconciliation. No automatic offline merge occurs.

## File spool

`from_bridge/` and `to_bridge/` each have one producer and one consumer. Immutable timestamp/sequence/UUID filenames end in `.json`. A producer writes a unique same-directory `.tmp`, closes it, then checks rename success. Python additionally flushes and fsyncs file contents. Receivers ignore `.tmp`, close the JSON file before processing, and write an immutable `.ack` only after safe handling. Python relays proposal receipts only after their coordinator outcome has been written to the inbound spool. The bridge acknowledges musical application only after verified readback/checkpoint update.

Producers remove only JSON files with durable receipt files. Receipts are retained indefinitely for replay/dedup; backups and branches are never automatically removed. Each direction has at most 64 active messages; queue exhaustion pauses rather than overwriting. Lua reads at most 64 queued messages per observation. Timestamp ordering is an optimization; event sequence/replay handles gaps and reordering.

Only Windows same-directory rename, interrupted-temp handling, and Lua/Python receipt interop have been tested. POSIX and machine-power-loss durability remain unverified. UUID filenames and one producer avoid overwrite races; local hostile writers are outside the security boundary. Lua standard IO lacks a stock fsync primitive, so reconciliation after a crash is essential.

## Scoped undo

The latest musical history entry for the authenticated actor is the candidate. Its track must be the requested track, currently owned, at the same revision and after-state. The inverse restores just that track's canonical before-state via targeted application; another track is never rewound. Ownership operations and earlier inverses are not undo candidates. Subsequent edits/handover invalidate the inverse. Native project-wide Undo is never invoked by the collaboration code.

## Future extension seam

Keep asset discovery outside the MIDI canonical model and bridge callback. A later asset manifest/transport can be attached to a separately versioned protocol after this workflow passes acceptance. There is no asset upload/download implementation in 0.1.
