Feature: Running without surprises
  The app spends money and makes promises about coverage, so degradation has to
  be visible rather than silent, and configuration has to be changeable without
  a redeploy.

  Scenario: A cold start does the useful work first
    Given a cold queue over a six month horizon
    When I look at what the worker will do next
    Then the nearest window is scheduled before the furthest
    And near-term windows refresh more often than distant ones

  Scenario: Reaching the JamBase cap degrades instead of spending
    Given JamBase is configured
    And the JamBase monthly cap is already reached
    When an artist lookup falls through to JamBase
    Then no JamBase call is made
    And the status page reports the quota as exhausted

  Scenario: Lidarr going down does not empty the library
    Given I have artists cached from an earlier sync
    And Lidarr is unreachable
    When the library sync runs
    Then the cached artists are still served
    And a health alert is sent to the services topic

  Scenario: Raising the alert threshold takes effect without a restart
    Given the alert threshold is 0.35
    When I raise the alert threshold to 0.75
    Then the new threshold is in effect immediately
    And it survives a restart

  Scenario: Moving house re-indexes rather than serving stale scores
    Given my home is set
    And the home horizon has been covered
    When I move home to Springfield
    Then home coverage is invalidated
    And the status page reports re-indexing
    And the old drive times are still on file

  Scenario: A missing API key is reported, not hidden
    Given Ticketmaster is not configured
    When I check the status page
    Then it reports Ticketmaster as not configured
    And no credential value appears anywhere in the response
