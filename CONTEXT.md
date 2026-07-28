# Football Opportunity Marketplace

A Telegram-based marketplace that helps adult amateur football participants discover relevant opportunities published in approved community chats.

## Language

**Player**:
An adult amateur footballer who is the primary MVP user and wants to find one or more relevant Open Matches in a selected Search Area.
_Avoid_: End user, football user

**Open Match**:
A specific upcoming football game with places available to individual Players.
_Avoid_: Team, tournament, transfer, permanent roster vacancy

**Game Search**:
A Player's intent to find one or more Open Matches that satisfy their confirmed Match Filters.
_Avoid_: Team Search, match listing

**Player Search**:
An organizer's intent to find individual Players for a specific Open Match.
_Avoid_: Game Search, Transfer Player Search

**Competition Search**:
The onboarding branch for finding either a Tournament or an opponent team; the Player must choose one of those two intents before selecting geography.
_Avoid_: Opponent Team Search

**Tournament Search**:
The intent to find a football Tournament.
_Avoid_: Opponent Search

**Opponent Search**:
The intent of a team representative to find another team for a football game.
_Avoid_: Tournament Search, Team Search

**Transfer Search**:
The onboarding branch for a long-term or seasonal move between teams; the user must choose whether to find a new team or find a Player for transfer.
_Avoid_: Player Search, one-off replacement

**New Team Search**:
A Player's intent to find a new team through a long-term or seasonal transfer.
_Avoid_: Game Search, Team Search

**Transfer Player Search**:
A team representative's intent to find a Player for a long-term or seasonal transfer.
_Avoid_: Player Search

**Match Filters**:
Criteria explicitly selected by a Player to determine which Open Matches are included in their results.
_Avoid_: Search settings, recommendation preferences

**Search Area**:
The country and city selected by a Player as the geographic boundary for matching Open Matches.
_Avoid_: Launch city, free-form location

**Bot Assistant**:
The conversational interface that interprets a Player's natural-language intent, helps select values, and persists only user-confirmed structured Match Filters.
_Avoid_: Model, agent, chatbot

**Telegram Language Hint**:
The optional Telegram app UI language tag received with a Player's update and used only to localize the initial interaction.
_Avoid_: System language, OS locale, confirmed language

**Conversation Language**:
The language explicitly selected or confirmed by a Player for communication with the Bot Assistant.
_Avoid_: Telegram Language Hint, system language

**Source Chat**:
A Telegram chat approved as a complete source stream while its continuing consent process covers every participant.
_Avoid_: Scraped chat, sampled chat, partially monitored group

**Source Message**:
Every account-visible message or post published in a Source Chat, regardless of author or football relevance; edits are revisions of the same Source Message.
_Avoid_: Selected Post, Match Post, Offer, Listing before classification

**Source Author**:
The Telegram account that published a Source Message, regardless of whether the account belongs to an administrator or an ordinary chat participant.
_Avoid_: Lead, prospect, future user
