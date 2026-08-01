# PROTOTYPE — Source Chat admission and protected-content boundary

This throwaway prototype answers one question: can the confirmed Source Chat
contract identify an already-accessible Telegram chat, keep its processing
boundary stable across address changes, and discard a protected event without
copying its body while update processing continues?

The live probe creates temporary chats containing only the configured
administrator account and the configured project bot. It generates message
bodies in memory, never reads them back, never prints or writes chat IDs,
usernames, invite links, message IDs, message bodies, credentials, or session
values. It attempts to delete the temporary chats at the end and emits only a
generic cleanup deferral when Telegram rate-limits deletion; a deferred cleanup
must be retried after the server wait. It does not inspect any existing message
or history.

Run from the repository root:

```bash
python3 prototypes/source_chat_admission/probe.py
```

Press `r` to run the bounded synthetic probe and `q` to quit. For a
non-interactive run, use:

```bash
python3 prototypes/source_chat_admission/probe.py --run
```

This code is prototype evidence, not production ingestion code. In particular,
its structural checks demonstrate that Telethon's default update checkpoint is
not atomic with the application record and that `StringSession` does not
serialize update states.
