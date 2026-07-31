# Football Opportunity Marketplace

A Telegram-based marketplace that helps adult amateur football participants discover relevant opportunities published in approved community chats.

## Language

### Participants

**Bot User**:
A Telegram user interacting with the Bot Assistant and selecting a terminal User Intent. The same Bot User may act as a Player, match organizer, team representative, coach, or referee in different flows.
_Avoid_: Player when the person may have another role, End user

**Player**:
An adult amateur footballer who is the primary MVP user and wants to find one or more relevant Open Matches in a selected Search Area.
_Avoid_: End user, football user

### User intents

**User Intent**:
A Bot User's confirmed terminal goal for one discovery flow. A User Intent is either a Search Intent or an Offer Intent.
_Avoid_: Intent Branch, Opportunity Type, menu label

**Search Intent**:
A User Intent expressing the counterpart or Opportunity that a Bot User wants to find.
_Avoid_: Offer Intent, Source Message type

**Offer Intent**:
A User Intent expressing the service role in which a Bot User is available while seeking compatible requests for that role.
_Avoid_: Search Intent, published service listing

**Intent Branch**:
A non-terminal onboarding choice that groups related User Intents and requires a subtype selection.
_Avoid_: User Intent, Opportunity Type

**Game Search**:
A Player's Search Intent to find one or more Open Matches that satisfy their confirmed Discovery Criteria.
_Avoid_: Team Search, match listing

**Player Search**:
A match organizer's Search Intent to find individual Players for a specific Open Match.
_Avoid_: Game Search, Transfer Player Search

**Competition Search**:
The Intent Branch for finding either a Tournament or an opponent team.
_Avoid_: Opponent Team Search

**Tournament Search**:
A Search Intent to find a football Tournament.
_Avoid_: Opponent Search

**Opponent Search**:
A team representative's Search Intent to find another team for a football game.
_Avoid_: Tournament Search, Team Search

**Transfer Search**:
The Intent Branch for a long-term or seasonal move between teams.
_Avoid_: Player Search, one-off replacement

**New Team Search**:
A Player's Search Intent to find a new team through a long-term or seasonal transfer.
_Avoid_: Game Search, Team Search

**Transfer Player Search**:
A team representative's Search Intent to find a Player for a long-term or seasonal transfer.
_Avoid_: Player Search

**Coaching Services**:
The Intent Branch for either finding a coach or offering coaching services.
_Avoid_: Coach Search

**Coach Search**:
A Search Intent to find a coach who is available to provide coaching services.
_Avoid_: Coaching Service Offer, Coach Request

**Coaching Service Offer**:
A coach's Offer Intent to find compatible Coach Requests.
_Avoid_: Coach Search, Coach Availability

**Refereeing Services**:
The Intent Branch for either finding a referee or offering refereeing services.
_Avoid_: Referee Search

**Referee Search**:
A Search Intent to find a referee who is available to officiate football games or competitions.
_Avoid_: Refereeing Service Offer, Referee Request

**Refereeing Service Offer**:
A referee's Offer Intent to find compatible Referee Requests.
_Avoid_: Referee Search, Referee Availability

### Classified opportunities

**Opportunity Type**:
The canonical market-side meaning assigned to an Opportunity Candidate.
_Avoid_: User Intent, Intent Branch, disposition

**Opportunity Candidate**:
One potentially independent request or offer interpreted from a Source Message that is not yet necessarily eligible for matching.
_Avoid_: Source Message, accepted Opportunity

**Opportunity**:
An accepted and normalized Opportunity Candidate with a durable identity across publication changes. Its Opportunity Publication State, not its existence, determines whether it is eligible for matching.
_Avoid_: Opportunity Candidate, Source Message, active listing

**Active Opportunity**:
An Opportunity whose Opportunity Publication State is `active` and which is therefore eligible for matching and new result delivery.
_Avoid_: accepted candidate, historical result, visible Source Message

**Opportunity Publication State**:
The current eligibility state of an Opportunity: `active`, `held_for_review`, `suppressed`, or `expired`.
_Avoid_: classification disposition, Opportunity Type, moderation reason

**Exact Repost Cluster**:
A set of distinct Source Messages from the same Source Publisher in one Source Chat that pass the exact-repost equality rule and are presented as one Opportunity result.
_Avoid_: message revision, transport duplicate, near duplicate

**Opportunity Attribute**:
An evidence-backed normalized fact derived from a Source Message for an Opportunity Candidate or accepted Opportunity. Its absence means unknown, not false.
_Avoid_: Discovery Criterion, unsupported inference, user preference

**Open Match**:
A specific upcoming football game with places available to individual Players.
_Avoid_: Team, tournament, transfer, permanent roster vacancy

**Player Match Availability**:
A Player's availability to join one or more one-off upcoming football games.
_Avoid_: Open Match, Player Transfer Availability

**Tournament**:
An announced football competition available for participation or registration.
_Avoid_: Opponent Request, Open Match

**Opponent Request**:
A team's request for another team to play; each request is both availability to play and a search for an opponent.
_Avoid_: Opponent Offer, Tournament

**Roster Vacancy**:
A long-term or seasonal place that a team wants to fill with a Player.
_Avoid_: Open Match, one-off replacement

**Player Transfer Availability**:
A Player's availability for a long-term or seasonal move to a new team.
_Avoid_: Player Match Availability, Roster Vacancy

**Coach Availability**:
A coach's offer to provide coaching services.
_Avoid_: Coach Request, Coaching Service Offer

**Coach Request**:
A Player's, team's, or organizer's request for coaching services.
_Avoid_: Coach Availability, Coach Search

**Referee Availability**:
A referee's offer to officiate football games or competitions.
_Avoid_: Referee Request, Refereeing Service Offer

**Referee Request**:
An organizer's request for a referee to officiate a football game or competition.
_Avoid_: Referee Availability, Referee Search

### Search and conversation

**Discovery Flow**:
One Bot User journey from a fresh Direction Menu through confirmed discovery inputs and one Search submission.
_Avoid_: Telegram chat history, saved search, result list

**Discovery Draft**:
The one durable, unfinished, and user-scoped state record for a Discovery Flow. It stores confirmed inputs, temporary editing state, and the current logical stage independently from Telegram messages.
_Avoid_: Active Chat View, completed search, per-intent draft cache

**Completed Search**:
An immutable Bot User-scoped record of one successful Search submission, its confirmed discovery inputs, and its ordered Result records, including a valid zero-result outcome.
_Avoid_: Discovery Draft, Saved Search, Active Result Context

**Discovery Criterion**:
A constraint explicitly confirmed by a Bot User for one discovery flow. An unopened, empty, or cleared optional criterion imposes no constraint and never asserts an Opportunity Attribute.
_Avoid_: Opportunity Attribute, inferred preference, classifier output

**Discovery Detail**:
A user-facing input or setting through which a Bot User confirms or clears one Discovery Criterion.
_Avoid_: Opportunity Attribute, unconfirmed suggestion, matching rule

**Confirmed Match**:
An active compatible Opportunity for which every selected Discovery Criterion is confirmed by accepted Opportunity Attributes.
_Avoid_: Possible Match, Partial Result, model similarity score

**Partial Result**:
A Player Search result in which a confirmed jointly available group contributes fewer Players than the requested total while every other selected Discovery Criterion is confirmed.
_Avoid_: Possible Match, combined reservation, full group

**Possible Match**:
An active compatible Opportunity with no conflicting selected Discovery Criterion and at least one selected criterion whose corresponding Opportunity Attribute is unknown.
_Avoid_: Confirmed Match, Variant with Difference, inferred fact

**Variant with Difference**:
An Opportunity with one explicitly identified, relaxable criterion conflict that is shown only after the Bot User asks to change or relax that criterion; it is not an ordinary match.
_Avoid_: Possible Match, hidden widening, model similarity

**Result Card**:
A localized Telegram presentation rendered from accepted Opportunity Attributes, structured matching evidence, current source metadata, and one usable Response Route.
_Avoid_: Source Message, free model summary, Active Chat View

**Active Result Context**:
The durable Bot User-scoped pointer to the one Completed Search whose Result Cards may be presented and discussed, together with its current Result identifier, absolute position, and result-screen revision.
_Avoid_: Active Chat View, Completed Search history, model-selected chat context

**Active Chat View**:
The current Telegram presentation of one logical bot screen. It may contain one message or a bounded group of result-card messages and is never the source of truth for a Discovery Draft.
_Avoid_: Discovery Draft, Telegram chat history, Completed Search, Active Result Context

**Event Time**:
One local date or bounded inclusive date range for a particular game, tournament, or event-specific request, with an optional exact local time or day part.
_Avoid_: Availability Window, Recurring Availability, message timestamp

**Availability Window**:
A bounded local date range in which one or more participants are available for one-off football games.
_Avoid_: Event Time, Recurring Availability, Seasonal Timing

**Recurring Availability**:
A repeating combination of weekdays and local times, optionally beginning on one local date.
_Avoid_: Event Time, Availability Window, Seasonal Timing

**Seasonal Timing**:
A long-term move's readiness now, local start date, or explicitly named season.
_Avoid_: Event Time, Recurring Availability, transfer deadline

**Team Format**:
The number of football players per side, including the goalkeeper when the goalkeeper is part of that format.
_Avoid_: total participant count, roster size, Venue Setting

**Playing Level**:
A self- or author-reported football playing level, not a verified credential, contract, or sporting title.
_Avoid_: qualification, licence, Play Intensity

**Venue Setting**:
Whether football activity takes place indoors, outdoors, or outdoors under a roof.
_Avoid_: Playing Surface, Opportunity Location, venue name

**Playing Surface**:
The evidence-backed material or surface category on which football activity takes place.
_Avoid_: Venue Setting, Opportunity Location

**Payment Status**:
Whether participation or a service is explicitly free, explicitly paid, or unknown; any stated amount establishes paid status.
_Avoid_: inferred currency, price preference

**Response Route**:
The automatically selected, evidence-supported path by which a Bot User can contact or reply to the source of an Opportunity.
_Avoid_: result card, Source Author identity, invented contact

**Search Area**:
A Bot User's explicitly confirmed geographic boundary for one discovery flow. It contains one country, one city, and either the whole city or one or more Sub-city Areas within it.
_Avoid_: Current location, country of residence, Launch city

**Suggested Country**:
An unconfirmed country shortcut based only on the Bot User's previously confirmed Search Area for the same User Intent.
_Avoid_: Detected Country, inferred country, current country

**Sub-city Area**:
A typed geographic refinement within one confirmed city, such as an administrative district, neighborhood, named locality, or the vicinity of a station, landmark, or address.
_Avoid_: District when the place is not an administrative district, Location constraint

**Location Mention**:
The exact Source Message text or source reference that expresses a place.
_Avoid_: Location Candidate, Opportunity Location, normalized location

**Location Candidate**:
One proposed normalized interpretation of a Location Mention that has not yet passed the location acceptance checks.
_Avoid_: Opportunity Location, Search Area, inferred fact

**Opportunity Location**:
Accepted normalized geography derived from a Source Message, preserving the most specific supported place and its verified parent hierarchy.
_Avoid_: Search Area, Location Candidate, Source Chat geography

**Bot Assistant**:
The conversational interface that interprets a Bot User's natural-language input, helps select values, and persists only user-confirmed structured selections.
_Avoid_: Model, agent, chatbot

**Telegram Language Hint**:
The optional Telegram app UI language tag received with a Bot User's update and used only to localize the initial interaction.
_Avoid_: System language, OS locale, confirmed language

**Conversation Language**:
The language explicitly selected or confirmed by a Bot User for communication with the Bot Assistant.
_Avoid_: Telegram Language Hint, system language

### Source ingestion

**Source Chat**:
A Telegram chat approved as a complete source stream while its continuing consent process covers every participant.
_Avoid_: Scraped chat, sampled chat, partially monitored group

**Source Message**:
Every account-visible message or post published in a Source Chat, regardless of author or football relevance; edits are revisions of the same Source Message.
_Avoid_: Selected Post, Match Post, Offer, Listing before classification

**Source Publisher**:
The Telegram principal visibly presented as publishing a Source Message, which may be a user account, chat, channel, or unknown principal.
_Avoid_: Source Author when Telegram hides the account, inferred administrator

**Source Author**:
A Telegram user account visibly attributable as the author of a Source Message. A Source Message may have a Source Publisher without an identifiable Source Author.
_Avoid_: Source Publisher, hidden administrator, Lead, prospect, future user

**Consent Withdrawal**:
A Source Author's explicit revocation of Source Chat processing consent for one named Source Chat.
_Avoid_: ordinary chat departure, Source Data Deletion Request

**Source Data Deletion Request**:
A verified request to erase retained Source Author data from one named Source Chat or, when explicitly requested, every enabled Source Chat.
_Avoid_: Consent Withdrawal, Telegram message deletion
