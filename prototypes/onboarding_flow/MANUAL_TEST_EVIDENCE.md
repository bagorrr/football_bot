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
| SETTINGS-SUPPORT-01 | Press `Поддержка` on Russian Settings | Before and after the action the logical stage remained `settings`; the current view stayed at message `#144`, revision `44`, protected and revision-matched. The prototype emitted `OPEN URL: https://telegram.me/myfootball_support_bot`; locale stayed `ru`, `completed_searches=1`, and `draft=None`. | Passed |
| SETTINGS-MODE-01 | Press `Режим` on Russian Settings | The logical stage changed `settings → mode`; message `#144` was replaced by protected message `#145`, revision `45`, with `active_view_matches_logical_revision=True`. The screen showed selected `✅ Поиск`, `Лента`, and Back. Locale stayed `ru`, `completed_searches=1`, and `draft=None`. | Passed |
| SETTINGS-FEED-01 | Press `Лента` in Mode | The prototype emitted `Feed will be available after the MVP.` The stage stayed `mode`; no message or logical revision was created (`#145`, revision `45` remained current), and locale, completed search, and empty draft state were unchanged. | Passed as placeholder behavior |
| SETTINGS-FEED-02 | Localization assessment of `SETTINGS-FEED-01` | Although the no-state-change placeholder behavior passed, its callback notice was English while the explicit account locale and surrounding UI were Russian. | Localization defect |
| SETTINGS-MODE-02 | Press already selected `✅ Поиск` in Mode | The stage stayed `mode`; no message or logical revision was created (`#145`, revision `45` remained current), and locale, completed search, and empty draft state were unchanged. The prototype emitted `Search is already the active MVP mode.` | Passed as no-op behavior |
| SETTINGS-MODE-03 | Localization assessment of `SETTINGS-MODE-02` | The already-active notice was English while the explicit account locale and surrounding UI were Russian. | Same localization defect as `SETTINGS-FEED-02` |
| SETTINGS-MODE-BACK-01 | Press Back from Mode | The logical stage changed `mode → settings`; message `#145` was replaced by protected message `#146`, revision `46`, with `active_view_matches_logical_revision=True`. Russian Settings rendered again; locale stayed `ru`, `completed_searches=1`, and `draft=None`. | Passed |
| SETTINGS-PREMIUM-01 | Press `Премиум` in Russian Settings | The prototype emitted `Premium will be available later (MVP placeholder).` The stage stayed `settings`; no message or logical revision was created (`#146`, revision `46` remained current), and locale, completed search, and empty draft state were unchanged. | Passed as placeholder behavior |
| SETTINGS-PREMIUM-02 | Localization assessment of `SETTINGS-PREMIUM-01` | The Premium placeholder notice was English while the explicit account locale and surrounding UI were Russian. | Same localization defect as `SETTINGS-FEED-02` |
| SETTINGS-BACK-01 | Press Back from Settings | The logical stage changed `settings → main_menu`; message `#146` was replaced by protected message `#147`, revision `47`, with `active_view_matches_logical_revision=True`. Russian Main Menu rendered with New Search, Search Results, and Settings; locale stayed `ru`, `completed_searches=1`, and `draft=None`. | Passed |
| MENU-02 | Invoke native `Menu` while already on Main Menu | Domain state stayed `main_menu` with locale `ru`, `completed_searches=1`, and `draft=None`. A fresh protected Main Menu message `#148`, revision `48`, replaced message `#147`; the active view matched the logical revision and the old view was deleted best effort. | Passed for functional idempotence; replacement observed |
| REPEAT-01 | Press `Новый поиск` after one completed search | A fresh `draft-2` was created with `origin=repeated`, `status=editing`, `stage=direction`, and `paused=False`; no prior search inputs were copied. The immutable completed-search count stayed `1`. Protected message `#149`, revision `49`, replaced the Main Menu. | Passed |
| REPEAT-MENU-01 | Invoke native `Menu` during active repeated onboarding at Direction | Per the confirmed contract, Main Menu did not open and the draft was not paused. The same Direction stage re-rendered as protected message `#150`, revision `50`; `draft-2` stayed `paused=False`, all draft fields stayed empty, and the completed-search count stayed `1`. | Passed |
| PROCESS-CORRECTION-01 | Correct the operator's pre-action statement that `Menu` would pause the draft | The confirmed pause action is Back from repeated-search Direction. Native `Menu` during any active onboarding stage only re-renders that stage. No prototype defect is assigned to `REPEAT-MENU-01`. | Evidence-process correction |
| REPEAT-BACK-01 | Press Back from repeated-search Direction | The logical stage moved to `main_menu`; `draft-2` remained present with `origin=repeated`, `status=editing`, `stage=direction`, and changed `paused=False → True`. All draft fields remained empty, completed-search count stayed `1`, and protected message `#151`, revision `51`, replaced Direction. | Passed |
| REPEAT-RESUME-01 | Send `/start` with paused `draft-2` | The same draft ID resumed at the same Direction stage; `paused=True → False`, no values were cleared or copied, and completed-search count stayed `1`. Protected message `#152`, revision `52`, replaced Main Menu and matched the logical revision. | Passed |
| REPEAT-BACK-02 | Press Back again after resuming `draft-2` | The same draft returned to paused Main Menu state: `paused=False → True`, ID and Direction stage were preserved, no values changed, and completed-search count stayed `1`. Protected message `#153`, revision `53`, replaced Direction. | Passed |
| PAUSED-SETTINGS-01 | Press `Настройки` while `draft-2` is paused | The logical surface changed `main_menu → settings`, while `draft-2` remained present at Direction with `paused=True` and all values unchanged. Locale stayed `ru`, completed-search count stayed `1`, and protected message `#154`, revision `54`, replaced Main Menu. | Passed |
| PAUSED-LANGUAGE-01 | Press `Язык` while `draft-2` is paused | The surface changed `settings → settings_language`; saved locale stayed `ru`, and `draft-2` remained paused at Direction with all fields unchanged. Completed-search count stayed `1`; protected message `#155`, revision `55`, replaced Settings. | Passed |
| PAUSED-LANGUAGE-02 | Press `🌐 Выбор языка` while `draft-2` is paused | The surface changed `settings_language → settings_language_free`; the screen expected language text and exposed only Back. Saved locale stayed `ru`, and `draft-2` remained paused at Direction with every field unchanged. Protected message `#156`, revision `56`, replaced the selector. | Passed |
| PAUSED-LANGUAGE-BACK-01 | Press Back from free-text language input | The surface returned `settings_language_free → settings_language`; uncommitted input was discarded, saved locale stayed `ru`, and paused `draft-2` remained unchanged at Direction. Protected message `#157`, revision `57`, replaced the free-text screen. | Passed |
| PAUSED-LANGUAGE-BACK-02 | Press Back from Settings language selector | The surface returned `settings_language → settings`; saved locale stayed `ru`, and paused `draft-2` remained unchanged at Direction. Completed-search count stayed `1`; protected message `#158`, revision `58`, replaced the selector. | Passed |
| PAUSED-SETTINGS-BACK-01 | Press Back from Settings with paused `draft-2` | The surface returned `settings → main_menu`; the same `draft-2` remained paused at Direction with all fields unchanged, locale stayed `ru`, and completed-search count stayed `1`. Protected message `#159`, revision `59`, replaced Settings. | Passed |
| REPEAT-SUPERSEDE-01 | Press current `Новый поиск` with paused `draft-2` | The paused draft was atomically superseded: `superseded_drafts` changed `0 → 1`, current draft ID changed `draft-2 → draft-3`, and the new repeated draft opened at Direction with `paused=False` and no copied inputs. Locale stayed `ru`, completed-search count stayed `1`, and protected message `#160`, revision `60`, replaced Main Menu. | Passed |
| DRAFT-EXPIRY-01 | Execute lab control `!expire-draft` with active `draft-3` | The draft expired and was removed (`draft=None`); Main Menu rendered as protected message `#161`, revision `61`. Explicit locale remained `ru`, completed-search count remained `1`, and `superseded_drafts` remained `1`. | Passed |
| DRAFT-POST-EXPIRY-01 | Send `/start` after `draft-3` expired | No expired draft resumed. A fresh `draft-4` with `origin=repeated`, `paused=False`, `status=editing`, `stage=direction`, and no copied inputs was created. Locale stayed `ru`, completed-search count stayed `1`, superseded count stayed `1`, and protected message `#162`, revision `62`, replaced Main Menu. | Passed |
| DRAFT-POST-EXPIRY-BACK-01 | Press Back from `draft-4` Direction | Main Menu rendered; the fresh post-expiry draft remained `draft-4`, changed `paused=False → True`, and stayed at Direction with no values. Locale, one completed search, and superseded count `1` were preserved. Protected message `#163`, revision `63`, replaced Direction. | Passed |
| RESULTS-BOUNDARY-01 | Press `Результаты поиска` on Main Menu | The prototype emitted its lab-only boundary notice that the search-results menu is intentionally undefined. No results screen, matching behavior, or result-card content opened or was defined; message `#163`, revision `63`, and all account, completed-search, and paused `draft-4` state remained unchanged. | Passed explicit scope boundary |
| SESSION-BOUNDARY-02 | Attempt to run `!duplicate-update` after `RESULTS-BOUNDARY-01` | The terminal process for the first model-backed TUI run no longer existed, so the command was not dispatched and no outcome was inferred. Because the prototype intentionally has no persistence, the in-memory state ending at message `#163` could not be restored. A new TUI process was started with the same one-command entrypoint and unchanged prototype logic; subsequent IDs explicitly belong to that fresh run. | Evidence boundary; not assigned as a prototype defect |
| DUPLICATE-UPDATE-01 | In the fresh run, select `Русский`, then execute `!duplicate-update` | Selecting Russian handled Telegram update `2`, created first-onboarding `draft-1` at Direction, and rendered message `#102`, revision `2`. Replaying update `2` was ignored: the same message/revision, locale `ru`, draft ID/stage, empty values, and zero completed searches remained unchanged. | Passed |
| VIEW-FAIL-ARM-01 | Execute lab control `!fail-render` at first-onboarding Direction | Only the one-shot `fail_next_render` flag changed `False → True`; message `#102`, revision `2`, locale `ru`, and `draft-1` at Direction remained unchanged. | Setup passed; failure trigger pending |
| VIEW-FAIL-01 | With `!fail-render` armed, press `Найти матч для себя` | Durable draft state advanced exactly once to `user_intent=game_search`, `stage=country`, and logical revision `3`. Replacement rendering failed, so visible message `#102`, revision `2`, remained protected with now-stale Direction controls; `active_view_matches_logical_revision=False`. The one-shot failure flag reset. | Passed failure containment; stale-view recovery pending |
| VIEW-FAIL-RECOVERY-01 | Press the still-visible `Найти матч для себя` callback from stale revision `2` | The stale callback was rejected rather than applying `game_search` again. Durable state remained at Country with no country selected; a fresh protected Country message `#103`, revision `4`, reconstructed the current logical screen and restored `active_view_matches_logical_revision=True`. | Passed |
| VIEW-KEEP-OLD-ARM-01 | Execute lab control `!keep-old` at Country | Only the one-shot `keep_next_old_view` flag changed `False → True`; protected Country message `#103`, revision `4`, locale `ru`, and draft values remained unchanged. | Setup passed; surviving-old-view trigger pending |
| VIEW-KEEP-OLD-01 | Send exact local alias `Россия` with `!keep-old` armed | Country `RU` was confirmed from the deterministic alias and the draft advanced to City. Protected message `#104`, revision `5`, became current and revision-matched. Old Country message `#103`, revision `4`, deliberately survived with its one Back callback still visible; the one-shot keep-old flag reset. | Passed setup for surviving stale callback |
| VIEW-STALE-01 | Execute `!stale` to press the surviving Back callback from old Country revision `4` | The stale Back was rejected and did not clear country or navigate to Direction. Draft stayed at City with country `RU`; a new protected City message `#105`, revision `6`, reconstructed the current screen and matched logical state. The deliberately surviving old message remained only as a lab artifact. | Passed |
| VIEW-CLEANUP-CURRENT-01 | Execute lab control `!cleanup-current` at City | Bot cleanup explicitly refused to delete the current Active Chat View. Message `#105` stayed protected, revision-matched, and not user-deleted; draft stayed at City with country `RU` and no city. | Passed |
| VIEW-USER-DELETE-01 | Execute lab control `!delete-current` at City | Active message `#105`, revision `6`, was marked deleted by the Bot User, while durable state remained `draft-1`, `game_search`, country `RU`, stage City, no city. The logical revision and all confirmed values remained unchanged. | Passed deletion containment; reconstruction pending |
| VIEW-USER-DELETE-RECOVERY-01 | Send `/start` after the Bot User deleted current City message `#105` | The same `draft-1` resumed at City with confirmed `game_search` and country `RU`; no new draft was created and no value was cleared. A new protected City message `#106`, revision `7`, replaced the user-deleted view and restored a revision-matched Active Chat View. | Passed |

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
9. Localize callback notices and placeholders to the explicit account locale;
   `SETTINGS-FEED-02`, `SETTINGS-MODE-03`, and `SETTINGS-PREMIUM-02` prove that
   Russian Settings currently emit English Feed, already-active, and Premium
   notices.

## Planned checks not yet executed

These are listed explicitly so the current passed observations cannot be
mistaken for complete validation:

- Remaining Settings checks: Mode, Feed placeholder, Premium placeholder, and
  every Back destination. Language and Support observations are recorded above.
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
