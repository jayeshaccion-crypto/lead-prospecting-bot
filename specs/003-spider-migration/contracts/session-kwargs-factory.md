# Contract: Session-Specific Kwargs Factory (FR-003)

**Purpose**: Ensure browser-only kwargs can never reach `FetcherSession` (TradeIndia). This is a structural guard — not a runtime check.

## Interface

```python
def _make_session_kwargs(
    sid: str,
    fetch_kwargs: dict,
    proxy: str | None,
) -> dict:
    """Return only the kwargs valid for the given session type.

    The sid is used as a dict lookup key, not an if/elif chain.
    A new sid MUST add an entry to `_SESSION_KWARG_FACTORIES` or
    a KeyError is raised at call site.
    """
    factory = _SESSION_KWARG_FACTORIES[sid]  # ← KeyError if unknown sid
    return factory(fetch_kwargs, proxy)
```

## Factory Map

```python
_SESSION_KWARG_FACTORIES: dict[str, Callable] = {
    "justdial_session": _build_stealth_kwargs,
    "indiamart_session": _build_stealth_kwargs,
    "tradeindia_session": _build_plain_kwargs,
}
```

### Stealth Factory (`_build_stealth_kwargs`)

Applies to: `justdial_session`, `indiamart_session`

```text
Input:  fetch_kwargs (dict from config), proxy (str | None)
Output: dict with keys:
          - timeout:  int   (from fetch_kwargs, default 90000)
          - proxy:    str   (required — KeyError if None)
          - wait:     int   (from fetch_kwargs page_delay * 1000, min 2000)
          - wait_selector:  str | None  (present only when fetch_kwargs has it)
          - wait_selector_state: str     ("visible", only alongside wait_selector)

Errors: ValueError if proxy is None (stealth sessions require proxy)

Note: The page-1-only rule for wait_selector is enforced at the CALL SITE in
`start_requests()` (the factory cannot know the page number): for `page_num > 1`
the call site strips `wait_selector` from the fetch_kwargs copy it passes in, so
later pages never carry wait_selector/wait_selector_state.
```

### Plain Factory (`_build_plain_kwargs`)

Applies to: `tradeindia_session`

```text
Input:  fetch_kwargs (dict from config), proxy (str | None — ignored)
Output: dict with keys:
          - timeout:  int   (from fetch_kwargs, default 90000)

Guarantee: Never returns proxy, wait, wait_selector, or any StealthySession-only kwarg.
```

## Invariant

- `_SESSION_KWARG_FACTORIES` is a module-level dict — read-only after module load
- No code path assembles kwargs in a shared dict and filters
- No code path branches on `if sid == X` to build kwargs
- Adding a new site requires adding a factory entry; omission fails at `KeyError`, not silently
