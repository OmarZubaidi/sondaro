Feature: Following my favorite artists around the world
  My top artists are the ones I'd build a holiday around, so for those I want
  every date they play anywhere on earth rather than the ones I could drive to.
  Here geography is the answer, not the filter.

  The ranking underneath moves on its own: affinity is recomputed on every sync
  and the scrobble source can be swapped for a better-covered one. A favorite
  must not drop off the page, or cost an API call twice, because they slipped a
  place while I was planning around them.

  Background:
    Given my home is set
    And Ticketmaster is configured
    And the border index is loaded
    And I follow my top 2 artists

  Scenario: A favorite on the other side of the world is still a date
    Given "Zola Jesus" is a favorite with 5000 scrobbles
    And "Zola Jesus" plays Tokyo
    When I look at who's touring
    Then "Zola Jesus" is listed
    And the Tokyo date is listed under Japan

  Scenario: Nothing is ranked down for being unreachable
    Given "Zola Jesus" is a favorite with 5000 scrobbles
    And "Zola Jesus" plays Tokyo
    When I look at who's touring
    Then no date is flagged
    And no date claims a drive time

  Scenario: Two favorites in one country ten days apart are one trip
    Given "Zola Jesus" is a favorite with 5000 scrobbles
    And "Beach House" is a favorite with 4000 scrobbles
    And "Zola Jesus" plays Berlin
    And "Beach House" plays Munich
    When I look at who's touring
    Then Berlin and Munich are the same trip
    And that trip covers 2 favorites

  Scenario: A border is not a distance
    Given "Zola Jesus" is a favorite with 5000 scrobbles
    And "Beach House" is a favorite with 4000 scrobbles
    And "Zola Jesus" plays Berlin
    And "Beach House" plays Amsterdam
    When I look at who's touring
    Then Berlin and Amsterdam are the same trip
    And that trip is named "Germany + Netherlands"

  Scenario: A country is not a place
    Given "Zola Jesus" is a favorite with 5000 scrobbles
    And "Beach House" is a favorite with 4000 scrobbles
    And "Zola Jesus" plays Boston
    And "Beach House" plays Los Angeles
    When I look at who's touring
    Then Boston and Los Angeles are different trips

  Scenario: Tightening what counts as one trip splits it
    Given "Zola Jesus" is a favorite with 5000 scrobbles
    And "Beach House" is a favorite with 4000 scrobbles
    And "Zola Jesus" plays Berlin
    And "Beach House" plays Munich
    When I look at trips of at most 5 days
    Then Berlin and Munich are different trips

  Scenario: Loosening it joins two that were apart
    Given "Zola Jesus" is a favorite with 5000 scrobbles
    And "Beach House" is a favorite with 4000 scrobbles
    And "Zola Jesus" plays Boston
    And "Beach House" plays Chicago
    When I look at trips within 1500 km
    Then Boston and Chicago are the same trip

  Scenario: A trip inside the US is named by state, not by country
    Given "Zola Jesus" is a favorite with 5000 scrobbles
    And "Zola Jesus" plays Boston
    When I look at who's touring
    Then that trip is named "MA"

  Scenario: An artist's own dates read as an itinerary, country by country
    Given "Zola Jesus" is a favorite with 5000 scrobbles
    And "Zola Jesus" plays Berlin
    And "Zola Jesus" plays Munich
    And "Zola Jesus" plays Tokyo
    When I look at who's touring
    Then Germany holds 2 dates
    And Germany is listed before Japan

  Scenario: My favorites are the ones I play most, not the ones named first
    Given "Aardvark Orchestra" is a favorite with 10 scrobbles
    And "Beach House" is a favorite with 4000 scrobbles
    And "Zola Jesus" is a favorite with 5000 scrobbles
    When I look at who's touring
    Then "Zola Jesus" is listed
    And "Beach House" is listed
    And "Aardvark Orchestra" is not listed

  Scenario: A favorite with nothing announced still gets a row
    Given "Zola Jesus" is a favorite with 5000 scrobbles
    And the worldwide search for "Zola Jesus" has run
    When I look at who's touring
    Then "Zola Jesus" is listed
    And "Zola Jesus" is not still being searched

  Scenario: Not having looked yet is not the same as nothing being on
    Given "Zola Jesus" is a favorite with 5000 scrobbles
    When I look at who's touring
    Then "Zola Jesus" is still being searched

  Scenario: Slipping a place keeps the tour, and buys nothing again
    Given "Zola Jesus" is a favorite with 5000 scrobbles
    And "Zola Jesus" plays Tokyo
    And I have been following "Zola Jesus"
    When "Zola Jesus" slips out of my top 2
    And I look at who's touring
    Then "Zola Jesus" is listed
    And "Zola Jesus" is marked as slipped
    And the Tokyo date is listed under Japan
    And no provider was called

  Scenario: Asking for a shorter list shortens it now
    Given "Zola Jesus" is a favorite with 5000 scrobbles
    And "Beach House" is a favorite with 4000 scrobbles
    And I have been following "Beach House"
    When I cut back to my top 1 artist
    And I look at who's touring
    Then "Zola Jesus" is listed
    And "Beach House" is not listed
