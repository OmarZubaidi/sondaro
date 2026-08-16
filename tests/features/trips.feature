Feature: Planning around a trip
  I pick a country first and cities afterwards, and my trips are usually
  multi-country. So anything inside a country I'm visiting stays fully in play,
  and a show just over a border is barely a detour rather than a disqualification.

  Background:
    Given my home is Home
    And Ticketmaster is configured
    And the border index is loaded

  Scenario: Every city in a visited country is equally in play
    Given I am going to France and Spain in September
    And "The National" is an artist I play constantly
    And "The National" plays Lyon during the trip
    And "The National" plays Barcelona during the trip
    When I look at the trip
    Then both shows score full marks on geography

  Scenario: A show just over the border is barely a detour
    Given I am going to France and Spain in September
    And "The National" is an artist I play constantly
    And "The National" plays Geneva during the trip
    When I look at the trip
    Then the Geneva show is recommended
    And it is flagged as not on my itinerary

  Scenario: A show far outside the trip is not a detour at all
    Given I am going to France and Spain in September
    And "The National" is an artist I play constantly
    And "The National" plays Berlin during the trip
    When I look at the trip
    Then the Berlin show is not recommended

  Scenario: Flexible dates let a show just outside the window through
    Given I am going to France and Spain in September
    And the trip has 3 days of slack either side
    And "The National" is an artist I play constantly
    And "The National" plays Lyon two days after the trip ends
    When I look at the trip
    Then the show is recommended
    And it is flagged as outside my dates

  Scenario: A trip to my own country searches only the cities I name
    Given my home country is the US
    And I am going to New York in September
    And "The National" is an artist I play constantly
    And "The National" plays New York during the trip
    And "The National" plays Los Angeles during the trip
    When I look at the trip
    Then the New York show is recommended
    And the Los Angeles show is not recommended

  Scenario: Naming a city in one country leaves the other country open
    Given my home country is the US
    And I am going to Canada and France, but have only booked Toronto
    And "The National" is an artist I play constantly
    And "The National" plays Toronto during the trip
    And "The National" plays Lyon during the trip
    When I look at the trip
    Then the Toronto show is recommended
    And the Lyon show scores full marks on geography

  Scenario: Strict dates admit nothing outside the window
    Given I am going to France and Spain in September
    And the trip dates are strict
    And "The National" is an artist I play constantly
    And "The National" plays Lyon two days after the trip ends
    When I look at the trip
    Then the show is not recommended
