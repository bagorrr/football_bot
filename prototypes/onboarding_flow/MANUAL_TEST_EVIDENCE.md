# PROVISIONAL — Manual Test Evidence for Issue #9

This is a factual working log for the throwaway prototype. It is **not** a
product verdict, ADR, Wayfinder update, or approved product conclusion.
Nothing from this file should be copied into product documentation or GitHub
until the Bot User gives final confirmation.

## Run identity

- Date: 2026-07-29
- Branch: `codex/prototype-issue-9-multilingual-onboarding`
- Pre-model prototype commit used earlier in this thread:
  `526b3d4` (`prototype: validate multilingual onboarding flow`)
- Model-backed prototype commit used for the current live run:
  `374dd3e3b216206a6dead23419bfacb9fd0155df`
- Command: `python3 prototypes/onboarding_flow/telegram_tui.py`
- Frozen prototype date: `2026-07-29`
- Model fallback: `gpt-5.6-sol` through isolated ephemeral Codex CLI
- Active tested locale: `ru`

## Evidence provenance and limits

- The pre-model evidence below comes from the exact Bot User messages and
  operator observations preserved in this Codex thread.
- The earlier pre-model terminal frame stream was not stored as a separate raw
  artifact. Entries without an exact state snapshot are marked
  `transcript-only`; no missing state is inferred.
- The model-backed run below comes from the live TUI frames. Each material
  action exposed the full relevant state after dispatch.
- From this point forward, new material TUI observations are appended during
  the same manual session.

## Durability guard

- Evidence IDs are stable and this log is append-only for the remainder of the
  prototype session. Corrections must add an explicit note instead of silently
  rewriting an earlier observation.
- Missing raw frames from the pre-model run must remain marked
  `transcript-only`; they must never be upgraded to a pass or failure by
  inference.
- Every later prototype fix and focused retest must cite the relevant evidence
  IDs from this file.
- This evidence file is locally versioned on the throwaway branch. It must not
  be pushed, copied into product documents, or turned into a product verdict
  before final Bot User confirmation.

## Earlier pre-model run preserved by the thread

| ID | Action or input | Preserved factual evidence | Evidence quality |
| --- | --- | --- | --- |
| PRE-01 | Select `Русский` | The onboarding conversation continued in Russian. | Thread + observed UI |
| PRE-02 | Select `Найти матч для себя` | The run entered the game-search geography path. | Thread + observed UI |
| PRE-03 | Send `Росси`, then `Росие` | These exact typo inputs were exercised before a model was attached. They prompted the discussion about obvious typo recognition. The exact old state frames are no longer available. | Transcript-only |
| PRE-04 | Back, then send `Рассея` | This exact typo and Back path were exercised while the prototype still had no model. The exact old state frame is no longer available. | Transcript-only |
| PRE-05 | Ask whether a model was attached | Inspection established that the old prototype had no model-backed interpretation. | Thread + code-version boundary |
| PRE-06 | Approve replacing local typo-specific behavior with the model-backed prototype | The later implementation boundary is commit `374dd3e`; the current live run started from that model-backed version. | Thread + Git history |

## Observed evidence

| ID | Action or input | Observed result and state | Provisional status |
| --- | --- | --- | --- |
| LANG-01 | Select `Русский` in the model-backed run | `account.locale='ru'`, `source='explicit'`; subsequent screens rendered in Russian. | Passed |
| DIR-00 | Send `рэфери` during the early Direction check | The operator mapped it to the `Судьи` button path; no model interpreted the free text, so this was not evidence of AI-native Direction handling. | Invalid as model test |
| NAV-00 | Back from the referee branch | Returned to Direction without testing or defining matching/results behavior. | Passed for observed navigation |
| DIR-01 | Send `Найти матч` on Direction | Text was rejected; no model interpretation ran; confirmed state did not change. | Deviation to address later |
| DIR-02 | Press `Найти матч для себя` | Confirmed `user_intent='game_search'` and entered Country. | Passed |
| GEO-01 | Send country typo `Русиа` | Model proposed and resolver accepted `RU`. | Passed |
| GEO-02 | Send city `Шэляба` for `RU` | Unresolved because the prototype resolver fixture for Russia exposes only `MOW` and `SPE`. | Fixture limitation; production dependency unresolved |
| GEO-03 | Send `спб` | Model proposed and resolver accepted `SPE`. | Passed |
| GEO-04 | Send `петрога` on the Search Area screen | Text was rejected; no area model interpretation ran; state did not change. | Deviation to address later |
| GEO-05 | Open the area checklist and select `Центральный район` | `temp_edit=['central']`; confirmed `area_mode` and `areas` remained empty. | Passed as temporary-state observation |
| GEO-06 | Back from the temporary area checklist | Temporary edit was discarded, but Back returned to the intermediate whole-city/area-choice screen. A second Back was required to reach City. | Deviation from canonical one-Back map |
| GEO-07 | Send `Москоу` prematurely on the intermediate Search Area screen | Text was rejected; city remained `SPE`; this exposed the extra Back step. | Expected for implemented screen, but screen itself is a deviation |
| GEO-08 | Back again, then send `Москоу` on City | Model proposed and resolver accepted `MOW`; city changed `SPE → MOW`; descendants were cleared. | Passed |
| GEO-09 | Open the Moscow area checklist | Prototype offered only `Центр`, `Север`, `Юг`, `Готово`, and Back; `temp_edit=[]`. | Fixture/UI limitation |
| GEO-10 | Back from the empty Moscow area checklist | Returned to the intermediate whole-city/area-choice screen instead of City. | Same one-Back deviation reproduced |
| GEO-11 | Send `арбат` on the Search Area screen | Text was rejected; no model interpretation ran; state did not change. | Deviation to address later |
| GEO-12 | Press `Весь город` as a temporary test bypass | Committed `area_mode='whole_city'`, `areas=[]`, and advanced to Required Date. | Passed for current implementation; UI is queued for replacement |
| DATE-01 | Open `Выбрать дату` | Prototype showed strict `YYYY-MM-DD` or range text input with Back. No calendar and no model interpretation exist. | Deviation to address later |
| DATE-02 | Send past date `2026-07-28` | Prototype incorrectly committed the date, advanced to `post_core`, hid Search, and showed a blocked-core notice. | Defect |
| DATE-03 | Send future date `2026-08-15` | Date replaced the prior value, `post_core` opened, and Search became available. | Passed for current implementation |
| DATE-04 | Back from `post_core` | Returned to Required Date and preserved the already confirmed date. Back itself did not commit anything. | Passed |
| DATE-05 | Select `Завтра` | Confirmed `2026-07-30`; Search available. | Passed for current implementation |
| DATE-06 | Select `Сегодня` | Confirmed `2026-07-29`; Search available. | Passed for current implementation |
| SEARCH-01 | Send failure completion before Search was submitting | Failure completion was ignored; state did not change. | Passed |
| SEARCH-02 | Press Search | Draft entered `submitting`; inline actions were disabled; typing indicator was on. | Passed |
| SEARCH-03 | Trigger duplicate Search while submitting | Duplicate action was ignored; no second submission or snapshot appeared. | Passed |
| SEARCH-04 | Complete submitting Search with technical failure | Draft returned to editable `post_core`; `game_search`, `RU`, `MOW`, whole-city area, and `2026-07-29` were preserved; Retry appeared. | Passed |
| SEARCH-05 | Retry, then complete with success | Exactly one immutable completed-search snapshot was stored; draft closed; native Menu returned; result content remained outside prototype scope. | Passed |
| MENU-01 | Press native Menu after Search | A new Main Menu view rendered with `Новый поиск`, `Результаты поиска`, and `Настройки`; `completed_searches=1`, `draft=None`. | Passed |
| SETTINGS-01 | Press `Настройки` | Settings rendered with `Язык`, `Поддержка`, `Режим`, `Премиум`, and Back; locale remained `ru`, `completed_searches=1`, `draft=None`. | Passed |
| SETTINGS-LANG-01 | Press `Язык` | Settings language selector rendered `English`, `Español`, `Français`, `Русский`, `🌐 Выбор языка`, and Back; saved locale remained `ru`, `completed_searches=1`, `draft=None`. | Passed |
| SETTINGS-LANG-02 | Press `🌐 Выбор языка` | Free-text language prompt opened with only Back. Saved locale remained `ru`; the screen advertised exact aliases plus `gpt-5.6-sol` fallback validated against the four supported locales. | Passed |
| SETTINGS-LANG-03 | Send `хочу на инглише` | Exact-alias check fell through to `gpt-5.6-sol`; model proposed `en`; local locale resolver accepted it; locale changed `ru → en`; Settings re-rendered in English; Telegram hint remained `ru`; `completed_searches=1`, `draft=None`. | Passed |
| SETTINGS-LANG-04 | Press `Language` after switching to English | The selector re-rendered in English with `🌐 Choose language` and Back; locale remained `en`; completed search remained present. | Passed |
| SETTINGS-LANG-05 | Press `Español` | Locale changed `en → es`; Settings re-rendered as `Ajustes` with `Idioma`, `Soporte`, `Modo`, `Premium`, and `Atrás`; Telegram hint remained `ru`; completed search remained present. | Passed |
| SETTINGS-LANG-06 | Press `Idioma` after switching to Spanish | The selector re-rendered in Spanish with `🌐 Elegir idioma` and `Atrás`; locale remained `es`; completed search remained present. | Passed |
| SETTINGS-LANG-07 | Press `Français` | Locale changed `es → fr`; Settings re-rendered as `Paramètres` with `Langue`, `Assistance`, `Mode`, `Premium`, and `Retour`; Telegram hint remained `ru`; completed search remained present. | Passed |
| SETTINGS-LANG-08 | Press `Langue` after switching to French | The selector re-rendered in French with `🌐 Choisir la langue` and `Retour`; locale remained `fr`; completed search remained present. | Passed |
| SETTINGS-LANG-09 | Press `Русский` | Locale changed `fr → ru`; Settings re-rendered in Russian; Telegram hint remained `ru`; completed search remained present; no draft was created. | Passed |
| VIEW-01 | Observe replacements across message `#112` through `#144` | Every observed current view was marked protected and had `active_view_matches_logical_revision=True`; replaced views became old and were marked `deleted best effort`. | Passed for normal replacement path |
| VIEW-02 | Invalid free text on button-only screens | Invalid text changed no confirmed domain value, but a replacement current view and new logical revision were rendered. | Observed; no contract deviation assigned yet |

## Deferred prototype fix queue

These items were explicitly requested during the manual session for the later
consolidated prototype-fix stage. They are not yet implemented and are not a
published product verdict.

1. Add model-backed free-text interpretation at Direction.
2. Replace the hard-coded production geography assumption with a real
   location-resolver/gazetteer dependency; prototype fixtures must remain
   clearly limited fixtures.
3. Replace the Search Area buttons and area checklist with one AI-native
   free-text prompt for district, station, street, landmark, venue, other
   place, or `весь город`; keep only Back.
4. Make Back from Search Area return directly to City and discard only
   unconfirmed area input.
5. Replace the date buttons and strict ISO input with AI-native free text for a
   date or bounded range; keep only Back.
6. Validate interpreted dates against the selected city's local calendar;
   past or ambiguous input must not change confirmed state or advance.
7. Run focused regression checks for typo/synonym resolution, ambiguity,
   model failure, invalid/past values, Back, and confirmed-state preservation.
8. Do not enter Details Hub until the date flow is fixed, retested, and
   explicitly approved by the Bot User.

## Planned checks not yet executed

These are listed explicitly so the current passed observations cannot be
mistaken for complete validation:

- Settings: Language selector, Support, Mode, Feed placeholder, Premium
  placeholder, and every Back destination.
- Repeated Menu behavior and Main Menu replacement.
- New repeated search, pause at repeated-search Direction, `/start` resume,
  superseding a paused draft, and 30-day expiry.
- Active-view render failure, user deletion of the current view, surviving old
  callbacks, stale callback rejection, and best-effort cleanup failure.
- Ambiguous, invalid, and model-failure paths for each eventual model-backed
  onboarding field.
- Remaining Conversation Languages: English, Spanish, and French.
- Remaining terminal User Intents and direction-specific core paths.
- Details Hub and every detail editor; intentionally deferred until the date
  flow is fixed and explicitly approved.
- Result cards, matching, and the results menu are intentionally excluded from
  this prototype ticket rather than merely untested.

## Evidence capture rule for the remainder of the session

For every material manual action, append:

1. the exact input or button;
2. the logical stage before and after;
3. the relevant confirmed and temporary state;
4. the visible user-facing result;
5. whether the observation matches the currently confirmed contract.
