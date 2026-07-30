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
| MODEL-CITY-AMBIGUOUS-01 | Send lab input `?ambiguous` at City for country `RU` | Interpretation returned ambiguous candidates `MOW` and `SPE`; the Russian fallback asked for one clearer choice. Draft remained at City with country `RU`, city `None`, and no descendants. A protected replacement message `#107`, revision `8`, exposed the fallback while staying revision-matched. | Passed |
| MODEL-CITY-INVALID-01 | Send lab input `?invalid` at City for country `RU` | Interpretation returned unresolved with no candidates; the Russian fallback asked for a rephrasing. Draft remained at City with country `RU`, city `None`, and no descendants. Protected message `#108`, revision `9`, replaced the prior fallback and matched logical state. | Passed |
| MODEL-CITY-FAIL-01 | Send lab input `?model-fail` at City for country `RU` | Interpretation returned `technical_failure` with `simulated_model_failure`; the Russian fallback said recognition was temporarily unavailable and confirmed data were preserved. Draft remained at City with country `RU`, city `None`, and no descendants. Protected message `#109`, revision `10`, replaced the prior fallback and matched logical state. | Passed |
| MODEL-CITY-BACK-01 | Press Back after City fallback checks | The screen returned to Country while the already confirmed country `RU` remained set; city stayed `None` and no descendants existed. Protected message `#110`, revision `11`, replaced City and matched logical state. | Passed navigation-only Back |
| MODEL-COUNTRY-AMBIGUOUS-01 | Send lab input `?ambiguous` at Country with confirmed country `RU` | Interpretation returned ambiguous candidates `RU`, `ES`, `FR`, and `DE`; the Russian fallback asked for one clearer choice. Existing country stayed `RU`, city stayed `None`, and the draft remained at Country. Protected message `#111`, revision `12`, replaced the screen and matched logical state. | Passed |
| MODEL-COUNTRY-INVALID-01 | Send lab input `?invalid` at Country with confirmed country `RU` | Interpretation returned unresolved with no candidates; the Russian fallback asked for a rephrasing. Existing country stayed `RU`, city stayed `None`, and the draft remained at Country. Protected message `#112`, revision `13`, replaced the prior fallback and matched logical state. | Passed |
| MODEL-COUNTRY-FAIL-01 | Send lab input `?model-fail` at Country with confirmed country `RU` | Interpretation returned `technical_failure` with `simulated_model_failure`; the Russian fallback said recognition was temporarily unavailable. Existing country stayed `RU`, city stayed `None`, and the draft remained at Country. Protected message `#113`, revision `14`, replaced the prior fallback and matched logical state. | Passed |
| MODEL-COUNTRY-BACK-01 | Press Back after Country fallback checks | The screen returned to Direction while confirmed `user_intent=game_search` and country `RU` remained unchanged; city stayed `None`. Protected message `#114`, revision `15`, replaced Country and matched logical state. | Passed navigation-only Back |
| MODEL-LANGUAGE-ENTRY-01 | Press Back from first-onboarding Direction | Language Selection rendered while saved locale remained `ru`; `draft-1` stayed at Direction with confirmed `game_search` and country `RU`, city `None`. Protected message `#115`, revision `16`, replaced Direction and matched logical state. | Passed navigation-only Back |
| MODEL-LANGUAGE-FREE-01 | Press `🌐 Выбор языка` on first-onboarding Language Selection | The surface changed `language → language_free`; saved locale stayed `ru`, and `draft-1` retained Direction, confirmed `game_search`, country `RU`, and city `None`. Protected message `#116`, revision `17`, expected language text and exposed only Back. | Passed |
| MODEL-LANGUAGE-AMBIGUOUS-01 | Send lab input `?ambiguous` at free-text Language with saved locale `ru` | Interpretation returned ambiguous candidates `en`, `es`, `fr`, and `ru`; the Russian fallback asked for one clearer choice. Saved locale stayed `ru`; the draft retained Direction, `game_search`, country `RU`, and city `None`. Protected message `#117`, revision `18`, replaced the screen and matched logical state. | Passed |
| MODEL-LANGUAGE-INVALID-01 | Send lab input `?invalid` at free-text Language with saved locale `ru` | Interpretation returned unresolved with no candidates; the Russian fallback asked for a rephrasing. Saved locale stayed `ru`; the draft retained Direction, `game_search`, country `RU`, and city `None`. Protected message `#118`, revision `19`, replaced the prior fallback and matched logical state. | Passed |
| MODEL-LANGUAGE-FAIL-01 | Send lab input `?model-fail` at free-text Language with saved locale `ru` | Interpretation returned `technical_failure` with `simulated_model_failure`; the Russian fallback said recognition was temporarily unavailable. Saved locale stayed `ru`; the draft retained Direction, `game_search`, country `RU`, and city `None`. Protected message `#119`, revision `20`, replaced the prior fallback and matched logical state. | Passed |

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

## 2026-07-30 consolidated prototype-fix boundary

This section is an append-only status correction to the earlier deferred queue.
The queue remains historically accurate as the plan at the time it was
written. Items 1–6 and 9 now have local throwaway-prototype implementations in
the working tree; they are **not yet Bot User approved**. Item 7 is now the
active focused-retest stage. Item 8 remains in force: Details Hub is still
deferred until the new date flow is manually retested and explicitly approved.

The implementation keeps the ten confirmed terminal intent IDs bounded, while
allowing the model to propose open country/city values with a canonical label
and IANA city timezone. This is a prototype mechanism, not a selected
production location dependency.

| ID | Action or input | Observed result and state | Provisional status |
| --- | --- | --- | --- |
| FIX-CONTRACT-01 | First post-fix smoke attempt: send `Шэляба` for confirmed country `RU` | The model returned `chelyabinsk`, `Челябинск`, and `Asia/Yekaterinburg`, but the state-machine city contract rejected the structurally valid payload because its city validator fell through without returning success. Country remained `RU`, city remained unset, and the Russian technical fallback rendered. | Implementation defect found; confirmed state preserved |
| FIX-CONTRACT-02 | Correct the city-contract return and replay the captured structured payload | The same payload advanced to Search Area with `city='chelyabinsk'`, `city_name='Челябинск'`, and `city_timezone='Asia/Yekaterinburg'`. | Local correction passed; live replay follows |
| FIX-DIR-01 | Fresh one-command run: select `Русский`, then send `Найти матч` at Direction | `gpt-5.6-sol` proposed `game_search`; the draft moved to `direction_confirm` with `user_intent=None`. The screen displayed «Я понял так: “Найти матч для себя”» with Confirm and Back. | Smoke passed; explicit user retest pending |
| FIX-DIR-02 | Press `Подтвердить` | Only after confirmation did `user_intent='game_search'` persist and Country open. | Smoke passed; explicit user retest pending |
| FIX-GEO-01 | Send exact country `Россия`, then typo/colloquial city `Шэляба` | Country resolved locally to `RU`; the live model resolved the city outside the old fixture to `chelyabinsk`, `Челябинск`, and `Asia/Yekaterinburg`. The draft advanced directly to one free-text Search Area screen. | Smoke passed; production dependency remains undecided |
| FIX-AREA-01 | Observe Search Area, then send `Центральный район` | The screen exposed only Back and asked for a district, metro, street, stadium, other place, or «весь город». The model committed `area_mode='areas'`, `areas=['Центральный район, Челябинск']`, and advanced to Required Date. | Smoke passed; explicit user retest pending |
| FIX-DATE-01 | Observe Required Date, then send `завтра` | The screen exposed only Back and requested a natural-language date or range. With selected-city timezone `Asia/Yekaterinburg` and local current date `2026-07-30`, the model resolved `2026-07-31`; the machine committed it and advanced to `post_core`. | Smoke passed; explicit user retest pending |
| FIX-DATE-PAST-01 | Back from `post_core`, then send `вчера` | The model returned unresolved; the draft stayed at Required Date, the previously confirmed `2026-07-31` remained unchanged, and the Russian fallback asked for different wording. | Smoke passed; explicit user retest pending |
| FIX-BACK-01 | Press Back from Required Date | Returned in one step to the single Search Area text screen; confirmed area and date remained unchanged. | Smoke passed; explicit user retest pending |
| FIX-BACK-02 | Press Back from Search Area | Returned in one step directly to City; no intermediate area-choice/checklist screen appeared. Confirmed descendants remained visible in state because Back is navigation-only. | Smoke passed; explicit user retest pending |
| FIX-GEO-OPEN-01 | Isolated smoke of Country input `Италия`, which is absent from the deterministic `COUNTRIES` examples | The model proposed `IT` with canonical label `Италия`; the state machine accepted the structured value and advanced to City with no city selected. | Open-geography prototype mechanism passed; production dependency remains undecided |
| FIX-DATE-RANGE-01 | Isolated Moscow-date smoke: send `с 5 по 7 августа` with local current date `2026-07-30` | The model proposed the inclusive range `2026-08-05..2026-08-07`, timezone `Europe/Moscow`; the local adapter accepted the future ordered range. | Smoke passed; explicit user retest pending |

The Settings callback localization change is implemented locally for Russian,
English, Spanish, and French Feed, active Search mode, and Premium notices, but
its focused post-fix manual replay has not yet been executed. No evidence above
is a prototype verdict or authorization to update product documentation,
GitHub, Wayfinder fog, or native dependencies.

## Bot User-directed focused retest

| ID | Action or input | Observed result and state | Provisional status |
| --- | --- | --- | --- |
| RETEST-DIR-01 | Select `Русский`, send `Найти матч`, then press `Подтвердить` | The model first proposed `game_search` while `user_intent` remained `None`. Only the explicit confirmation persisted `user_intent='game_search'`, cleared `pending_direction`, and advanced to Country. | Passed; awaiting continuation of focused retest |
| RETEST-COUNTRY-01 | Send typo `Русиа` at Country | The model proposed `RU` with canonical label `Россия`; the state machine confirmed the country and advanced to City. `user_intent='game_search'` remained unchanged and all city/descendant fields remained empty. | Passed |
| RETEST-CITY-01 | Send colloquial typo `Шэляба` for confirmed country `RU` | The model resolved a city absent from the old fixture as `chelyabinsk`, canonical label `Челябинск`, timezone `Asia/Yekaterinburg`. The state machine advanced to the single free-text Search Area screen with only Back; country and intent were preserved. | Passed |
| RETEST-AREA-01 | Send `Центральный район` at the single free-text Search Area screen | The model resolved `chelyabinsk-tsentralny-district` with label `Центральный район, Челябинск`; the machine committed `area_mode='areas'`, advanced to Required Date, and preserved intent/country/city. The date screen accepted text and exposed only Back. | Passed |
| RETEST-DATE-RANGE-01 | Send `с 5 по 7 августа` with selected city `Челябинск`, timezone `Asia/Yekaterinburg`, and local current date `2026-07-30` | The model resolved inclusive dates `2026-08-05..2026-08-07`; the machine committed the range and advanced to `post_core` with Back, Details, and Search. Geography and all other confirmed state remained unchanged. | Passed; past-date preservation check follows |
| RETEST-DATE-BACK-01 | Press Back from `post_core` after confirming the range | Returned to Required Date in one step. The confirmed range `2026-08-05..2026-08-07`, selected-city timezone, area, city, country, and intent were all preserved. | Passed |
| RETEST-DATE-PAST-01 | Send `вчера` with local current date `2026-07-30` and an existing confirmed range | The model returned unresolved; the stage remained Required Date and the confirmed `2026-08-05..2026-08-07` range plus all geography remained unchanged. The visible Russian notice was generic («не удалось надёжно сопоставить…») and did not state that the date was in the past. | State preservation passed; user-facing reason is a prototype copy deviation |

### Past-date copy correction

The Bot User explicitly approved correcting the prototype message after
`RETEST-DATE-PAST-01`. The adapter now asks the model to extract a clear date
even when it is in the past; the local calendar validator converts that
proposal into `unresolved` with `failure_code='past_date'`. The Russian screen
then says: «Эта дата уже прошла. Напишите сегодняшнюю или будущую дату либо
период; подтверждённые данные не изменены.»

An isolated post-change replay of `вчера` produced that exact reason and did
not advance from Required Date. The active user-directed TUI process still had
the old code loaded and must be restarted before the corrected copy can be
replayed there; its in-memory draft cannot be persisted by design.

After restart, the operator reconstructed the same confirmed
`game_search → Россия → Челябинск → Центральный район → 2026-08-05..2026-08-07`
route and sent `вчера`. The live TUI rendered the corrected Russian
past-date message, recorded `failure_code='past_date'`, stayed at Required
Date, and preserved the confirmed range and all geography. This closes the
prototype copy deviation from `RETEST-DATE-PAST-01`; explicit Bot User approval
of the overall date stage is still pending.

The Bot User then explicitly confirmed the corrected date stage after observing
the natural-language future range, navigation-only Back, past-date rejection,
clear localized reason, and preservation of the previously confirmed range.
This is an intermediate HITL approval only; it is not the final prototype
verdict. The earlier gate on Details Hub is therefore lifted for the next
manual-test phase.

| RETEST-DETAILS-HUB-01 | After date-stage approval, reopen `post_core` and press `Детали` | Details Hub opened for `game_search` with Time, Team Format, Positions, Game Levels, Surface Type, Surface, and Payment in that order, followed by Back and Search. Every criterion was unset; the confirmed intent, geography, and date range were preserved unchanged. | Passed initial hub entry; editor checks follow |
| RETEST-DETAIL-TIME-ENTRY-01 | Press `Время` in Details Hub | Time editor opened with Exact Time, Morning, Afternoon, Evening, Night, Any, and Back. `criteria` remained empty and `detail_key='time'`; all core values remained unchanged. | Passed editor entry |
| RETEST-DETAIL-TIME-EXACT-ENTRY-01 | Press `Указать точное время` | A localized `HH:MM` text prompt opened with only Back. `nested_kind='exact_time'`; confirmed `criteria` stayed empty and the selected-city core remained unchanged. | Passed nested entry; invalid/valid inputs follow |
| RETEST-DETAIL-TIME-INVALID-01 | Send invalid exact time `25:99` | The machine stayed in exact-time input and correctly left confirmed `criteria` empty. However, the replacement screen repeated only the original prompt and showed no visible explanation that the value was invalid; the reason existed only in laboratory `LAST EFFECT`. | State preservation passed; user-facing validation defect |

The Bot User explicitly approved correcting
`RETEST-DETAIL-TIME-INVALID-01`. The throwaway state now carries a transient
`input_notice='invalid_exact_time'` for that replacement frame, and the
localized exact-time prompt renders «Введите корректное время от 00:00 до
23:59». An isolated post-change replay confirmed the visible warning and
`criteria={}`. A restarted live-TUI replay is still required because the
running process had the prior module loaded.

A fresh live TUI replay reconstructed a valid Moscow game-search core, opened
Details → Time → Exact Time, and sent `25:99`. The visible Russian warning
rendered exactly as intended, the stage stayed `detail_nested`, and
`criteria={}` remained unchanged. This closes the prototype defect from
`RETEST-DETAIL-TIME-INVALID-01`; valid exact-time commit is still pending.

| RETEST-DETAIL-TIME-VALID-01 | Send valid exact local time `19:30` | The machine committed `criteria.time={'exact':'19:30'}`, cleared nested/editing state, and returned to Details Hub. The hub displayed `Время: 19:30`; all core values and unrelated criteria were preserved. | Passed |
| RETEST-DETAIL-MULTI-ENTRY-01 | Press `Формат команд` | The multi-select opened with temporary `temp_edit=[]`, choices `5x5` through `11x11`, Done, and Back; confirmed criteria still contained only exact Time. The explanatory line `Temporary selection — Done commits, Back discards.` was English in an otherwise Russian screen. | Editor state passed; localization defect |

The Bot User explicitly approved correcting the Details localization defect.
The temporary multi-select and immediate single-select explanations are now
localized in all four conversation languages. The same focused inspection also
found and localized the prototype-only Seasonal and Schedule explanations,
summaries, nested headings, buttons, and free-text prompts so later Details
checks do not repeat the same hard-coded-English defect. Product documentation
and canonical copy remain unchanged.

A fresh live TUI replay reached `Формат команд` with preserved exact Time. The
screen now showed «Выбор временный — “Готово” сохраняет, “Назад” отменяет.»;
`temp_edit=[]` and confirmed criteria were otherwise unchanged. This closes the
localization defect from `RETEST-DETAIL-MULTI-ENTRY-01`; Back/Done semantics
remain to be exercised.

| RETEST-DETAIL-MULTI-TEMP-01 | Select `7x7` in Team Format | The checkbox changed to selected and only `temp_edit=['7x7']` changed. Confirmed `criteria` still contained exact Time only; no Team Format was committed and all core values remained unchanged. | Passed temporary-edit isolation; Back follows |
| RETEST-DETAIL-MULTI-BACK-01 | Press Back with temporary Team Format `7x7` | Returned to Details Hub, cleared editing/temp state, and left Team Format unset. Confirmed exact Time `19:30` and every core value were preserved. | Passed |
| RETEST-DETAIL-MULTI-REOPEN-01 | Reopen `Формат команд` after discarding temporary `7x7` | The editor reopened with every checkbox clear and `temp_edit=[]`; confirmed exact Time `19:30` and all core values remained unchanged. | Passed; discarded temporary value did not reappear |
| RETEST-DETAIL-MULTI-RESELECT-01 | Select `7x7` after reopening Team Format | The checkbox changed to selected and `temp_edit=['7x7']`; confirmed `criteria` still contained only exact Time `19:30`, with all core values unchanged. | Passed temporary-edit isolation; explicit Done commit follows |
| RETEST-DETAIL-MULTI-DONE-01 | Press Done with temporary Team Format `7x7` | The machine committed only `criteria.team_format=['7x7']`, returned to Details Hub, and displayed `Формат команд: 7x7`. Exact Time `19:30`, required core values, and unrelated criteria were preserved; temporary editing state was cleared. | Passed |
| RETEST-DETAIL-POSITIONS-ENTRY-01 | Open `Позиции` from Details Hub | The localized multi-select opened with all four positions clear, `temp_edit=[]`, Done, and Back. Confirmed Time `19:30`, Team Format `7x7`, and all core values remained unchanged. | Passed; selection semantics follow |
| RETEST-DETAIL-POSITIONS-TEMP-01 | Select `Защитник` | The checkbox changed to selected and `temp_edit=['defender']`; confirmed criteria still contained only Time `19:30` and Team Format `7x7`, with all core values unchanged. | Passed temporary-edit isolation |
| RETEST-DETAIL-POSITIONS-MULTI-01 | Add `Полузащитник` to the temporary selection | Both checkboxes were selected and `temp_edit=['defender','midfielder']`; confirmed criteria and all core values remained unchanged before Done. | Passed multi-selection and temporary-edit isolation |
| RETEST-DETAIL-POSITIONS-DONE-01 | Press Done with `Защитник` and `Полузащитник` selected | The machine committed only `criteria.positions=['defender','midfielder']`, returned to Details Hub, and displayed both localized values. Time `19:30`, Team Format `7x7`, required core values, and unrelated criteria were preserved. | Passed |
| RETEST-DETAIL-LEVELS-ENTRY-01 | Open `Уровни игры` from Details Hub | The localized multi-select opened with Beginner, Intermediate, Advanced, and Pro all clear, `temp_edit=[]`, Done, and Back. All confirmed criteria and core values remained unchanged. | Passed; selection semantics follow |
| RETEST-DETAIL-LEVELS-TEMP-01 | Select `Средний` | The checkbox changed to selected and `temp_edit=['average']`; no confirmed criteria or core values changed before Done. | Passed temporary-edit isolation |
| RETEST-DETAIL-LEVELS-DONE-01 | Press Done with `Средний` selected | The machine committed only `criteria.playing_levels=['average']`, returned to Details Hub, and displayed the localized value. All previously confirmed criteria and required core values were preserved. | Passed |
| RETEST-DETAIL-VENUE-ENTRY-01 | Open `Тип площадки` from Details Hub | The localized editor opened with Indoor, Outdoor, and Covered outdoor all clear, `temp_edit=[]`, Done, and Back. All confirmed criteria and core values remained unchanged. | Passed entry state; selection semantics follow |
| RETEST-DETAIL-VENUE-TEMP-01 | Select `На улице` | The checkbox changed to selected and `temp_edit=['outdoor']`; confirmed criteria and core values remained unchanged before Done. | Passed temporary-edit isolation |
| RETEST-DETAIL-VENUE-DONE-01 | Press Done with `На улице` selected | The machine committed only `criteria.venue_setting=['outdoor']`, returned to Details Hub, and displayed the localized value. All previously confirmed criteria and required core values were preserved. | Passed |
| RETEST-DETAIL-SURFACE-ENTRY-01 | Open `Покрытие` from Details Hub | The localized editor opened with Natural grass, Artificial turf, Hard court, and Wood/parquet all clear, `temp_edit=[]`, Done, and Back. All confirmed criteria and core values remained unchanged. | Passed entry state; selection semantics follow |
| RETEST-DETAIL-SURFACE-TEMP-01 | Select `Искусственный газон` | The checkbox changed to selected and `temp_edit=['artificial_turf']`; confirmed criteria and core values remained unchanged before Done. | Passed temporary-edit isolation |
| RETEST-DETAIL-SURFACE-DONE-01 | Press Done with `Искусственный газон` selected | The machine committed only `criteria.playing_surface=['artificial_turf']`, returned to Details Hub, and displayed the localized value. All previously confirmed criteria and required core values were preserved. | Passed |
| RETEST-DETAIL-PAYMENT-ENTRY-01 | Open `Оплата` from Details Hub | The localized editor opened with Free and Paid clear, `temp_edit=[]`, Done, and Back. All confirmed criteria and core values remained unchanged. | Passed entry state; selection semantics follow |
| RETEST-DETAIL-PAYMENT-TEMP-01 | Select `Платно` | The checkbox changed to selected and `temp_edit=['paid']`; confirmed criteria and core values remained unchanged before Done. | Passed temporary-edit isolation |
| RETEST-DETAIL-PAYMENT-DONE-01 | Press Done with `Платно` selected | The machine committed only `criteria.payment=['paid']`, returned to Details Hub, and displayed the localized value. The hub now showed values for all seven optional Details fields; all required core values and previously confirmed criteria were preserved. | Passed |
| RETEST-DETAIL-HUB-BACK-01 | Press Back from Details Hub with all seven optional fields populated | Returned one level to the post-core choice (`Назад / Детали / Поиск`), not into the date editor. All seven optional criteria and all required core values remained confirmed and unchanged. | Passed |
| RETEST-DETAIL-HUB-RESUME-01 | Reopen Details Hub from the post-core choice | The hub immediately displayed all seven previously committed localized values; the underlying criteria and all required core values were unchanged. | Passed editor resumption |
| RETEST-POSTCORE-BACK-DATE-01 | Press Back from the post-core choice with all Details fields populated | Returned directly to the AI-native required-date text stage. The previously accepted date, all seven optional criteria, and all earlier core values remained present; Back itself caused no invalidation. | Passed |
| RETEST-DATE-EDIT-PRESERVE-DETAILS-01 | Send `послезавтра` after returning from post-core | The bounded model resolved the city-local date to `2026-08-01` and returned to post-core. Only `required_date` changed from `2026-07-31`; all seven optional Details criteria, country, city, and area remained unchanged. | Passed selective preservation |
| RETEST-DATE-EDIT-DETAILS-VISUAL-01 | Reopen Details after changing required date | The hub displayed the same seven localized values, while full state showed the new date `2026-08-01`; no optional criterion or earlier core value changed. | Passed |
| RETEST-BACK-TO-CITY-PRESERVE-01 | Traverse Back from Details Hub through post-core, required date, and area to City | Each Back moved exactly one confirmed stage (`details_hub → post_core → required_date → areas → city`). Moscow, whole-city area, date `2026-08-01`, and all seven optional criteria remained unchanged throughout; navigation alone caused no dependent invalidation. | Passed |
| RETEST-CITY-CHANGE-INVALIDATION-01 | Send `Питер` at City after a fully populated Moscow draft | The bounded model resolved Saint Petersburg and advanced to Area. The city change cleared the old whole-city area, required date, and exact Time `19:30`; it preserved non-temporal Team Format, Positions, Playing Levels, Venue Setting, Playing Surface, and Payment. Country and intent remained unchanged. | Passed dependency-aware invalidation |
| RETEST-CITY-CHANGE-WHOLE-CITY-01 | Send `весь город` for Saint Petersburg | The exact localized alias committed `area_mode='whole_city'` and advanced to required date. Required date and exact Time remained cleared, while all six non-temporal Details criteria stayed unchanged. | Passed |
| RETEST-CITY-CHANGE-NEW-DATE-01 | Send `завтра` after selecting whole Saint Petersburg | The bounded model resolved `2026-07-31` in the selected city's timezone and returned to post-core. The six non-temporal Details criteria remained unchanged; exact Time stayed unset as required by the prior city invalidation. | Passed |
| RETEST-CITY-CHANGE-DETAILS-VISUAL-01 | Open Details after rebuilding the Saint Petersburg core | The hub visibly showed Time as unset and the other six optional values unchanged. Full state matched the dependency-aware invalidation exactly; no unrelated value was lost. | Passed |
| RETEST-ACTIVE-MENU-TEXT-01 | Send native reply text `Menu` while Details Hub onboarding is active | The machine replaced the Active Chat View with the same current Details stage and did not pause, clear, or leave the draft. This matches the confirmed active-onboarding Menu rule in `docs/product/onboarding-flow.md`; the initial apparent failure to open Main Menu was therefore expected behavior, not a defect. | Passed |
| RETEST-SEARCH-SUBMIT-FULL-DRAFT-01 | Press Search from a valid Saint Petersburg draft after dependency-aware invalidation | The draft atomically entered `submitting`, inline actions disappeared, and the typing indicator became active. Required core values and the six surviving non-temporal Details criteria remained in the submitting snapshot. No result content or results menu was defined. | Passed |
| RETEST-SEARCH-SUCCESS-BOUNDARY-01 | Deliver the system search-success event | The machine stored one immutable completed-search snapshot, closed the draft, restored the native Menu reply button, and rendered only the explicit prototype boundary. It did not define matching, result-card content, or a results menu. | Passed |
| RETEST-INACTIVE-MENU-TEXT-01 | Send native reply text `Menu` after the completed-search boundary | The machine rendered a fresh Russian Main Menu with New Search, Search Results, and Settings. There was no active draft; the native Menu reply button remained available. | Passed |
| RETEST-LANGUAGE-EN-SETTINGS-01 | Select `English` in Main Menu → Settings → Language | The saved conversation locale changed `ru → en`, the destination Settings screen immediately rendered in English, the completed-search count stayed `1`, and no draft was created or altered. | Passed |
| RETEST-LANGUAGE-EN-MAIN-MENU-01 | Press Back from English Settings | A fresh English Main Menu rendered with New search, Search results, and Settings; history count and native Menu availability were preserved. | Passed |
| RETEST-LANGUAGE-EN-DIRECTION-01 | Press New search from the English Main Menu | A fresh repeated-search draft opened at Direction with all six localized top-level choices, Back, and the AI-native free-text prompt. No values from the completed Russian search were copied; history remained intact. | Passed |
| RETEST-INTENT-EN-PLAYER-PROPOSAL-01 | Send `I need players for my match` at English Direction | The bounded model proposed terminal intent `player_search` and rendered an English confirmation screen. `user_intent` remained unset and only `pending_direction` changed, so the model did not persist its own proposal. | Passed explicit-confirmation boundary |
| RETEST-INTENT-EN-PLAYER-CONFIRM-01 | Press Confirm on the English direction proposal | The machine persisted `user_intent='player_search'`, cleared the pending proposal, and rendered the intent-specific English country prompt. | Passed |
| RETEST-INTENT-EN-PLAYER-BACK-01 | Press Back from the `player_search` country prompt | Returned directly to the English Direction menu. The confirmed `player_search` value remained durable; no geography existed to clear. | Passed navigation-only Back |
| RETEST-BRANCH-EN-COMPETITION-ENTRY-01 | Open `Tournament or opponent team` | The English Competition branch rendered Tournament, Opponent team, and Back. The branch changed only transient navigation state; confirmed `player_search` remained unchanged. | Passed namespace boundary |
| RETEST-INTENT-EN-TOURNAMENT-01 | Select `Tournament` in the English Competition branch | The terminal choice changed `user_intent` from `player_search` to `tournament_search`, rendered the intent-specific English country prompt, and cleared all downstream inputs (which were already empty). | Passed |
| RETEST-INTENT-EN-TOURNAMENT-BACK-01 | Press Back from the Tournament country prompt | Returned to the owning English Competition branch and preserved confirmed `tournament_search`. | Passed owning-branch Back |
| RETEST-INTENT-EN-OPPONENT-01 | Select `Opponent team` in the English Competition branch | The terminal choice changed `user_intent` from `tournament_search` to `opponent_search` and rendered the intent-specific English country prompt. | Passed |
| RETEST-INTENT-EN-RETURN-MAIN-01 | Traverse Back from Opponent country through Competition branch and repeated-search Direction | Each Back followed the owning stage. Direction Back rendered the English Main Menu and paused draft-2 with confirmed `opponent_search`; history remained unchanged. | Passed |
| RETEST-LANGUAGE-ES-SETTINGS-01 | Select `Español` while draft-2 is paused | The saved locale changed `en → es` and the Settings screen immediately rendered in Spanish. The paused `opponent_search` draft and completed-search history remained unchanged. | Passed |
| RETEST-LANGUAGE-ES-MAIN-MENU-01 | Press `Atrás` from Spanish Settings | A fresh Spanish Main Menu rendered with Nueva búsqueda, Resultados de búsqueda, and Ajustes. The paused draft and completed history were preserved. | Passed |
| RETEST-LANGUAGE-ES-NEW-SEARCH-01 | Press `Nueva búsqueda` with draft-2 paused | The machine atomically superseded paused draft-2, incremented `superseded_drafts` to `1`, and opened a fresh empty Spanish repeated-search Direction draft. Completed history remained intact and no prior intent or inputs were copied. | Passed |
| RETEST-BRANCH-ES-TRANSFER-ENTRY-01 | Open `Fichajes` | The Spanish Transfer branch rendered Buscar un nuevo equipo, Buscar un jugador para fichar, and Atrás. The fresh draft still had no terminal `user_intent`. | Passed |
| RETEST-INTENT-ES-NEW-TEAM-01 | Select `Buscar un nuevo equipo` | The machine persisted `user_intent='new_team_search'` and rendered the intent-specific Spanish country prompt. | Passed |
| RETEST-INTENT-ES-NEW-TEAM-BACK-01 | Press `Atrás` from the New Team country prompt | Returned to the owning Spanish Transfer branch and preserved confirmed `new_team_search`. | Passed |
| RETEST-INTENT-ES-TRANSFER-PLAYER-01 | Select `Buscar un jugador para fichar` | The terminal choice changed `user_intent` from `new_team_search` to `transfer_player_search` and rendered the intent-specific Spanish country prompt. | Passed |

## Cross-locale code matrix and focused model smokes

These checks were run after the manual Russian, English, and Spanish paths
above. The structural matrix was a one-off in-memory Python invocation; it did
not add a maintained test suite or modify prototype state. The model smokes
used the same bounded `gpt-5.6-sol` adapter as the live TUI.

| Evidence ID | Action | Observed state/effect | Assessment |
| --- | --- | --- | --- |
| RETEST-LOCALE-MATRIX-01 | Run the same Direction, branch, model-proposal confirmation/rejection, country-entry, and owning-Back transitions for all four locales and all ten terminal intents in fresh in-memory states | The matrix completed `888` assertions across `ru`, `en`, `es`, and `fr`. Every locale exposed the same canonical action graph; all ten intents reached Country only after explicit confirmation, rejection returned to Direction without persisting an intent, and Country Back returned to the owning branch or Direction while preserving the confirmed intent. | Passed `4 locales × 10 intents`; structural parity only, not a translation-quality verdict |
| RETEST-MODEL-ES-DIRECTION-01 | Send live Spanish Direction text `Soy entrenador y quiero ofrecer mis servicios` | `gpt-5.6-sol` proposed `coaching_service_offer` in `4185 ms`. The Spanish confirmation screen rendered `Ofrecer servicios de entrenador`; `user_intent` remained unset and only `pending_direction` changed. | Passed live multilingual interpretation and explicit-confirmation boundary |
| RETEST-MODEL-ES-DIRECTION-CONFIRM-01 | Press `Confirmar` on the Spanish proposal | The machine persisted `user_intent='coaching_service_offer'`, cleared the pending proposal, set the owning branch to `coaching_services`, and rendered the Spanish intent-specific country prompt. | Passed |
| RETEST-MODEL-FR-DIRECTION-01 | Send live French Direction text `Je suis arbitre et je propose mes services` | `gpt-5.6-sol` proposed `refereeing_service_offer` in `5046 ms`. The French confirmation screen rendered `Proposer des services d’arbitrage`; `user_intent` remained unset and only `pending_direction` changed. | Passed live multilingual interpretation and explicit-confirmation boundary |
| RETEST-MODEL-FR-DIRECTION-CONFIRM-01 | Press `Confirmer` on the French proposal | The machine persisted `user_intent='refereeing_service_offer'`, cleared the pending proposal, set the owning branch to `refereeing_services`, and rendered the French intent-specific country prompt. | Passed |
| RETEST-MODEL-ES-CORE-SMOKE-01 | In an isolated Spanish `game_search`, submit `Espna`, `Madrd`, `barrio de Salamanca`, and `del 5 al 7 de agosto` through Country, City, Area, and Date | The model/local contract accepted `ES`/`España`, `madrid`/`Madrid` with `Europe/Madrid`, area `barrio de Salamanca` with `whole_city=False`, and inclusive date range `2026-08-05..2026-08-07`. The machine reached `post_core` with the expected confirmed values. | Passed selected Spanish open-field and typo smoke |
| RETEST-MODEL-FR-CORE-SMOKE-01 | In an isolated French `game_search`, submit `Frnce`, `Pari`, `tout Paris`, and `du 5 au 7 août` through Country, City, Area, and Date | The model/local contract accepted `FR`/`France`, `paris`/`Paris` with `Europe/Paris`, `Tout Paris` with `whole_city=True`, and inclusive date range `2026-08-05..2026-08-07`. The machine reached `post_core` with the expected confirmed values. | Passed selected French open-field and typo smoke |
| RETEST-LIVE-CHECKPOINT-01 | Stop after the focused multilingual checks | The live TUI remains at the French Country stage with `account.locale='fr'`, `draft-5`, owning branch `refereeing_services`, confirmed `user_intent='refereeing_service_offer'`, and no geography yet entered. | Checkpoint recorded; no product verdict inferred |

The matrix proves shared state-machine behavior for the enumerated paths. The
two live phrases and two isolated core-field paths prove only those selected
model inputs; they do not establish the naturalness of every translation or
the interpretation of arbitrary wording.

## 2026-07-30 provisional closure audit

This audit compared the current throwaway branch and the complete evidence log
with issue #9, the full resolution of issue #7, the accepted product documents,
and ADR 0005. It is factual audit evidence, not the prototype verdict or
authorization to publish product changes.

| Evidence ID | Audit action | Observed result | Assessment |
| --- | --- | --- | --- |
| AUDIT-SCOPE-01 | Compare the branch with current `origin/main` | All branch additions are confined to the five files under `prototypes/onboarding_flow/`. `origin/main` is an ancestor of the throwaway branch, and no product or production file is changed. | Passed throwaway/scope boundary |
| AUDIT-ISSUE-01 | Read live issue #9, issue #7 resolution, and native dependencies | Issue #9 remains open, assigned to `bagorrr`, and has no resolution comment. Its only native blocker is closed issue #7; it currently blocks no issue. | Correct pre-verdict tracker state |
| AUDIT-CORE-MATRIX-01 | Compare `DATE_REQUIRED`, every direction-specific Details order, and the Area → Required Date/Post-core routing with the confirmed documents; render the Details entry screens for every locale/intent combination | Required-date membership and all ten Details orders matched the confirmed tables. `40` locale/intent core routes and `260` localized top-level detail screens rendered with the expected action structure. | Passed structural coverage; specialized editor behavior is not fully covered by this matrix |
| AUDIT-SETTINGS-I18N-01 | Replay Feed, already-active Search mode, and Premium callback notices for all four locales | All `12` notices used their active Conversation Language and changed no domain state. | Current code closes the earlier Settings-notice localization defect; focused live replay was replaced by exhaustive in-memory comparison |
| AUDIT-MODEL-FALLBACK-MATRIX-01 | Replay ambiguous, unresolved, and technical-failure outcomes for Language, Direction, Country, City, Area, and Date in every locale | All `72` cases preserved the complete account and Discovery Draft state and rendered the locale-specific fallback prefix. | Passed structural failure preservation |
| AUDIT-PLAYING-LEVELS-01 | Compare `DETAIL_SPECS['playing_levels']` with the accepted eight-value Playing Level vocabulary | The prototype exposes only `novice`, `average`, `high`, and `professional`; it omits `below_average`, `above_average`, `very_high`, and `master`. | Unresolved prototype defect; the prior four-value manual pass did not validate the confirmed screen |
| AUDIT-SCHEDULE-INTERVAL-01 | Submit reversed exact Schedule interval `20:00-19:00` | The prototype accepted the reversed pair into temporary state as `['20:00','19:00']` instead of rejecting it. | Unresolved prototype validation defect |
| AUDIT-LANGUAGE-FREE-I18N-01 | Render free-text Language input in Russian, Spanish, and French | Each localized prompt is followed by the same English `[PROTOTYPE MODEL]` explanatory paragraph. | Unresolved prototype localization defect |
| AUDIT-SUBCITY-CONTRACT-01 | Compare the Bot User-approved one-prompt AI-native Area screen with the accepted location contract | The current screen correctly exposes only Back and accepts a place or whole-city phrase, but each accepted non-city answer replaces `areas` with one display label. The accepted document still supports a union of several normalized Sub-city Areas with stable IDs, types, parents, `Добавить ещё`, and `Готово`. | Product consequence unresolved: no final rule yet says how several areas work in the buttonless AI-native flow |
| AUDIT-REQUIRED-DATE-CONTRACT-01 | Compare the current required-date screen with the accepted date contract | The current one-prompt AI-native date/range screen with only Back is the behavior explicitly approved during this HITL session; the accepted documents still describe Today, Tomorrow, and Choose-date controls. | Validated prototype change awaiting final confirmation and durable documentation, not a current code defect |
| AUDIT-OPTIONAL-DATE-CONTRACT-01 | Compare Seasonal Timing and Schedule start-date editors with their accepted screens | The prototype uses strict `YYYY-MM-DD` text prompts, while the accepted contract specifies a local single-date picker for Seasonal Timing and Today/Tomorrow/Choose date/Any for Schedule start date. These editors were not manually exercised in the current HITL run. | Unresolved prototype fidelity and coverage gap; the required-date approval did not explicitly change these optional editors |
| AUDIT-FIRST-LANGUAGE-COPY-01 | Compare Welcome and free-text Language screens with `language-onboarding.md` | The prototype Welcome is a shorter paraphrase rather than the reviewed first-message copy, and the free-text prompt omits its reviewed examples in addition to the English laboratory paragraph above. | Unresolved copy-fidelity gap for a ticket specifically validating multilingual onboarding |
| AUDIT-ASSET-CAPTURE-01 | Compare local and remote throwaway branch state | Local `HEAD` is `5594a44`, thirteen commits ahead of the remote prototype branch at `374dd3e`; this evidence file also has uncommitted additions. Its run-identity header still names the earlier model-backed commit and Russian locale. | Expected pre-capture state; commit metadata, evidence disposition, push, and asset link must be finalized only after the closure gaps and final confirmation |

The older “Planned checks not yet executed” section remains append-only
historical evidence. Later manual rows plus the audit matrices close its
Settings, lifecycle, Active Chat View, fallback, locale, terminal-intent, and
core-routing items. The remaining blockers are the explicit defect and
contract-gap rows above; matching, result cards, and the results menu remain
deliberately out of scope.

## 2026-07-30 confirmed closure corrections

Before changing the Area contract, the complete pre-change prototype and
append-only evidence were committed as `7561aac` and pushed to
`codex/prototype-issue-9-multilingual-onboarding`. This is the durable
before-state for comparison; it includes the provisional audit above and does
not contain the corrections below.

The Bot User then confirmed this prototype behavior: one AI-native Area message
may name one or several Sub-city Areas; the model returns an ordered normalized
list; whole city is mutually exclusive with that list; an accepted answer
completes Search Area immediately; and the only inline action on the prompt is
Back. This is confirmation for the throwaway prototype, not yet a published
product verdict.

| Evidence ID | Correction/check | Observed result | Assessment |
| --- | --- | --- | --- |
| FIX-AREA-CONTRACT-01 | Replace the single-label Area payload with `whole_city` plus an ordered normalized `areas` list containing stable canonical ID, localized label, language-neutral geographic type, country parent, and city parent | The pure machine now persists the complete validated list. Whole city requires an empty list; a place selection requires a non-empty list; candidate IDs must match the list exactly and in order. | Corrected to the confirmed prototype behavior |
| FIX-AREA-PROMPT-I18N-01 | Render Area in Russian, English, Spanish, and French | Each prompt now explicitly says that one message may contain one or several places, mentions whole city, waits for text, and exposes only Back. | Passed structural localization check |
| FIX-AREA-CONTRACT-NEGATIVE-01 | Submit four malformed laboratory payloads: whole city mixed with places, empty non-city list, candidate/list cardinality mismatch, and wrong city parent | All four were rejected as invalid interpretation contracts; confirmed country, city, Area, date, and criteria remained unchanged. | Passed local-authority and failure-preservation check |
| FIX-AREA-LIVE-MODEL-01 | Send live Russian text `Арбат и Хамовники` with Russia/Moscow already confirmed | `gpt-5.6-sol` returned two ordered normalized objects (`arbat`, `khamovniki`) in `6993 ms`; the local contract accepted both and advanced immediately to Required Date. | Passed the focused live multi-area seam; this is not a gazetteer-quality verdict |
| FIX-AREA-WHOLE-CITY-01 | Send exact reviewed alias `весь город` | The deterministic resolver returned `candidate_ids=['whole_city']`, `whole_city=True`, and `areas=[]`; the machine committed city-level Search Area immediately. | Passed mutual-exclusion path |
| FIX-PLAYING-LEVELS-01 | Restore the accepted eight-value Playing Level vocabulary and render it across every applicable locale/intent editor | The value order is Beginner, Below average, Average, Above average, High, Very high, Master, Professional with reviewed Russian, English, Spanish, and French labels. All `32` applicable editor screens exposed all eight canonical values. | Corrected and passed |
| FIX-SCHEDULE-INTERVAL-01 | Submit `20:00-19:00`, `20:00-20:00`, malformed text, and `19:00-20:00` | Reversed, zero-length, and malformed intervals preserved temporary and confirmed state and showed a localized inline warning. The ascending interval was stored temporarily and returned to the parent Time submenu. | Corrected and passed |
| FIX-LANGUAGE-FREE-I18N-01 | Render the free-text Language screen in all four locales | The laboratory model paragraph now uses Russian, English, Spanish, or French consistently with the active Conversation Language; each screen still exposes only Back. | Corrected and passed |
| RETEST-CLOSURE-CORE-DETAIL-MATRIX-01 | Rerun the cross-locale core routing and every top-level detail entry after the corrections | All `40` locale/intent core routes passed; `260` localized detail editors rendered; the `32` Playing Level editors contained the exact eight-value list. | Passed regression matrix |
| RETEST-CLOSURE-FALLBACK-MATRIX-01 | Rerun ambiguous, unresolved, and technical-failure outcomes for Language, Direction, Country, City, Area, and Date in all four locales | All `72` cases preserved complete account and Discovery Draft state and rendered the localized fallback marker. | Passed regression matrix |
| RETEST-CLOSURE-ONE-COMMAND-01 | Run `python3 prototypes/onboarding_flow/telegram_tui.py --no-clear` from the repository root | Model preflight succeeded, the localized first Active Chat View rendered, full state was visible, and EOF exited cleanly. | Passed one-command startup |

The old long-running TUI process was deliberately stopped because Python had
loaded the pre-correction modules into memory. A fresh process is required for
the next manual check. The optional Seasonal Timing and Schedule start-date
editors and the first-message/free-language copy-fidelity gap remain unchanged
pending separate one-question-at-a-time confirmation.

## 2026-07-30 confirmed AI-native optional dates

The Bot User confirmed the following prototype behavior: the Seasonal Timing
start-date and Schedule start-date nested editors accept natural-language text
in the active Conversation Language and expose only Back; Schedule also accepts
localized `Any`; an accepted answer returns to the parent detail editor as
temporary state; and only the parent `Done` action commits the detail. The
saved `b42d3ac` artifact is the durable state immediately before this change.
This is confirmed prototype behavior, not yet a published product verdict.

| Evidence ID | Correction/check | Observed result | Assessment |
| --- | --- | --- | --- |
| FIX-OPTIONAL-DATE-SCREENS-01 | Render Seasonal Timing start-date and Schedule start-date prompts in Russian, English, Spanish, and French | All `8` screens use localized natural-language guidance, wait for model-backed text, and expose exactly one Back action. The old strict `YYYY-MM-DD` guidance and Schedule `Any` button are absent. | Corrected to confirmed prototype behavior |
| FIX-SEASONAL-DATE-LIVE-01 | Send live Russian Seasonal Timing text `с 15 августа` with Moscow selected | `gpt-5.6-sol` returned the single local date `2026-08-15` in `10598 ms`. The local validator accepted it as temporary `start_date`; confirmed criteria remained unchanged until parent `Done`. | Passed focused live seam |
| FIX-SCHEDULE-START-LIVE-01 | Send live Russian Schedule text `начиная с 20 августа` with Moscow selected | `gpt-5.6-sol` returned `clear=False` and the single local date `2026-08-20` in `4914 ms`. The machine returned to the Schedule parent with only temporary `start_date`; confirmed Schedule remained unchanged until parent `Done`. | Passed focused live seam |
| FIX-SCHEDULE-ANY-01 | Send exact localized `Any` phrases in all four locales | `неважно`, `any`, `cualquiera`, and `peu importe` resolved deterministically to canonical `any`. Each cleared only temporary Schedule `start_date`; weekdays, day parts, exact interval, confirmed Schedule, and unrelated criteria were preserved until `Done`. | Passed `4` locale aliases and scoped clearing |
| FIX-OPTIONAL-DATE-BACK-DONE-01 | Exercise accepted value → parent, parent `Done`, and nested Back for both optional-date editors | Accepted values returned to the parent as temporary state. `Done` committed only the edited detail. Back restored the nested snapshot and left confirmed criteria unchanged. | Passed ADR 0005 temporary-state semantics |
| FIX-OPTIONAL-DATE-VALIDATION-01 | Submit a range and a past date where one future local start date is required | Both invalid candidates were rejected without changing temporary or confirmed state. A live `с 1 июля` model call also returned `unresolved/past_date` in `11247 ms`. | Passed local temporal authority and visible failure path |
| FIX-OPTIONAL-DATE-FALLBACK-01 | Replay ambiguous, unresolved/past, and technical-failure outcomes for both optional-date fields in every locale | All `24` cases preserved the complete Discovery Draft, retained the one-button nested editor, and rendered the localized fallback marker. | Passed failure preservation |
| FIX-REQUIRED-DATE-CANDIDATE-ID-01 | Recheck required range `с 5 по 7 августа` after introducing the stricter optional-date schemas | The first regression probe exposed `invalid_model_result`: the model could encode correct endpoints using more than one internal candidate ID. The local adapter now derives one canonical ID from validated `start/end`. A repeat live call accepted `2026-08-05..2026-08-07` as `2026-08-05/2026-08-07` in `4416 ms`. | Regression found from evidence and corrected; required-date behavior restored |
| RETEST-OPTIONAL-DATE-CORE-DETAIL-01 | Rerun the full cross-locale core/detail matrix | All `40` locale/intent core routes, `260` detail entry screens, and `32` eight-value Playing Level editors passed. | Passed regression matrix |
| RETEST-OPTIONAL-DATE-FALLBACK-01 | Rerun fallback preservation including Language, Direction, Country, City, Area, required Date, Seasonal start date, and Schedule start date | All `96` locale/field/outcome cases preserved account and draft state and rendered their localized fallback. | Passed expanded regression matrix |
| RETEST-OPTIONAL-DATE-ONE-COMMAND-01 | Run `python3 prototypes/onboarding_flow/telegram_tui.py --no-clear` from the repository root | Model preflight succeeded, the first Active Chat View rendered with full state, and EOF exited cleanly. | Passed one-command startup |

The pre-change interactive process was stopped before these checks because it
had loaded older modules into memory. The first-message/free-language reviewed
copy-fidelity gap remains unchanged and is the next unresolved closure item.

## 2026-07-30 repeat closure audit

The Bot User requested a complete repeat audit after confirming synchronization
of the canonical AI-native Search Area and date contracts. This section records
only the prototype checks and correction; it is not the final product verdict.

| Evidence ID | Audit/correction | Observed result | Assessment |
| --- | --- | --- | --- |
| AUDIT-REPEAT-STRUCTURAL-01 | Rerun Language, all fixed branches and terminal intents, core routes, Details, Back, semantic invalidation, lifecycle, Menu/Settings, Active Chat View, Search recovery, fallbacks, and the results boundary against commit `a323fc8` | The one-off in-memory audit completed `907` checks: `260` detail screens, `32` eight-value Playing Level screens, and `96` fallback cases with both state-preservation and localized-copy assertions. | Passed the complete structural ticket matrix before the model-adapter correction below |
| AUDIT-REPEAT-DATE-EMPTY-ID-01 | Send live required-date text `с 5 по 7 августа` | The model returned valid endpoints `2026-08-05..2026-08-07` but an empty internal `candidate_ids` list. The adapter returned `technical_failure/invalid_model_result`; the state machine correctly preserved all confirmed state. | Found a model-adapter normalization defect; the visible failure path remained safe |
| FIX-DATE-CANDIDATE-EMPTY-01 | Extend date candidate normalization to a valid empty internal ID list as well as one or several internal IDs | Synthetic valid required-date payloads with zero, one, and two internal IDs all normalized to the single canonical ID `2026-08-05/2026-08-07`; malformed types remain subject to the existing contract checks. | Corrected without changing product semantics or state transitions |
| RETEST-REPEAT-LIVE-MODEL-01 | Repeat four live seams: Russian free Direction, Russian multi-area, Russian required range, and Spanish typo city `Madrd` | All `4/4` were accepted and locally validated. The required range normalized to `2026-08-05/2026-08-07`; the city resolved to Madrid with `Europe/Madrid`. | Passed focused live model seam after the correction |
| FIX-REPEAT-DATE-FALLBACK-COPY-01 | Compare the past-date fallback for required Date, Seasonal Timing start date, and Schedule start date in all four locales | Each field now asks only for values it accepts: required Date permits a date or range; Seasonal Timing permits one date; Schedule permits one date or localized `Any`. The Search Area Back laboratory effect now also describes the confirmed one-message contract rather than obsolete temporary area edits. | Corrected misleading failure/laboratory copy without changing state |
| RETEST-REPEAT-TARGETED-01 | Rerun the affected fallback, Search Area Back, syntax, and one-command paths | All `12` localized past-date cases preserved account and draft state and used field-valid guidance. Search Area Back preserved the confirmed Search Area, required date, and criteria. Python compilation and `python3 prototypes/onboarding_flow/telegram_tui.py --no-clear` passed with model preflight and a protected current view. | Passed targeted regression after the two narrow corrections |
