# Football Opportunity Marketplace

A Telegram-based marketplace that helps adult amateur football participants discover relevant opportunities published in approved community chats.

## Language

**Player**:
An adult amateur footballer who is the primary MVP user and wants to find one or more relevant Open Matches in a selected Search Area.
_Avoid_: End user, football user

**Open Match**:
A specific upcoming football game with places available to individual Players.
_Avoid_: Team, tournament, transfer, permanent roster vacancy

**Match Filters**:
Criteria explicitly selected by a Player to determine which Open Matches are included in their results.
_Avoid_: Search settings, recommendation preferences

**Search Area**:
The country and city selected by a Player as the geographic boundary for matching Open Matches.
_Avoid_: Launch city, free-form location

**Bot Assistant**:
The conversational interface that interprets a Player's natural-language intent, helps select values, and persists only user-confirmed structured Match Filters.
_Avoid_: Model, agent, chatbot

**Source Chat**:
A Telegram chat explicitly included by the product owner as an approved source of new messages.
_Avoid_: Scraped chat, monitored group

**Source Message**:
A message published in a Source Chat and admitted to classification; it is not necessarily a relevant football opportunity.
_Avoid_: Match Post, Offer, Listing before classification

**Source Author**:
The Telegram account that published a Source Message, regardless of whether the account belongs to an administrator or an ordinary chat participant.
_Avoid_: Lead, prospect, future user
