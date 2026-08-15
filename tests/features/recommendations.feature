Feature: Recommending shows worth going to
  Sondaro ranks a show by how much I actually listen to the artist and how far
  I'd realistically travel on that particular day. Driving hours decide
  reachability, not miles: DC and Millbrook are 129 miles apart on a map and much
  closer from behind a wheel.

  Background:
    Given my home is Home
    And Ticketmaster is configured

  Scenario: A favourite playing Fairview on a Tuesday is worth the drive
    Given "The National" is an artist I play constantly
    And "The National" plays Fairview on a Tuesday
    When I look at what's on near home
    Then "The National" is recommended
    And it carries no flags

  Scenario: Somewhere too far just sinks, without being singled out
    Given "The National" is an artist I play constantly
    And "The National" plays Springfield on a Saturday
    And "The National" plays Millbrook on a Saturday
    When I look at what's on near home
    Then it ranks below anything closer to home
    And it carries no flags

  Scenario: A mid-tier artist is not worth crossing the state for
    Given "Passing Interest" is an artist I rarely play
    And "Passing Interest" plays Fairview on a Tuesday
    When I look at what's on near home
    Then "Passing Interest" is not recommended

  Scenario: A mid-tier artist in town is absolutely worth it
    Given "Passing Interest" is an artist I rarely play
    And "Passing Interest" plays Springfield on a Tuesday
    When I look at what's on near home
    Then "Passing Interest" is recommended

  Scenario: The same show ranks higher on a Saturday than a Tuesday
    Given "The National" is an artist I play constantly
    And "The National" plays Fairview on a Tuesday
    And "The National" plays Fairview on a Saturday
    When I look at what's on near home
    Then the Saturday show outranks the Tuesday show

  Scenario: Without routing, drive times are estimates and say so
    Given OpenRouteService is not configured
    And "The National" is an artist I play constantly
    And "The National" plays Fairview on a Tuesday
    When I look at what's on near home
    Then "The National" is recommended
    And it is flagged as an estimated drive time
