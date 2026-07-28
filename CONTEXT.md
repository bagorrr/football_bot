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
A Player's Search Intent to find one or more Open Matches that satisfy their confirmed Match Filters.
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
An accepted and normalized Opportunity Candidate eligible for matching to compatible User Intents.
_Avoid_: Opportunity Candidate, Source Message

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

**Match Filters**:
Criteria explicitly selected by a Player to determine which Open Matches are included in their results.
_Avoid_: Search settings, recommendation preferences

**Search Area**:
A Bot User's explicitly confirmed geographic boundary for one discovery flow. It contains one country, one city, and either the whole city or one or more Sub-city Areas within it.
_Avoid_: Current location, country of residence, Launch city

**Suggested Country**:
An unconfirmed country shortcut based only on the Bot User's previously confirmed Search Area for the same User Intent.
_Avoid_: Detected Country, inferred country, current country

**Sub-city Area**:
A typed geographic refinement within one confirmed city, such as an administrative district, neighborhood, named locality, or the vicinity of a station, landmark, or address.
_Avoid_: District when the place is not an administrative district, Location Filter

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

**Source Author**:
The Telegram account that published a Source Message, regardless of whether the account belongs to an administrator or an ordinary chat participant.
_Avoid_: Lead, prospect, future user
