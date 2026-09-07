# IPL Intelligence Rankings

This module is an original ranking model inspired by the publicly described principles of the ICC player and team rankings. It is not the official ICC algorithm.

## Rating scale
Player and team ratings use a 0-1000 scale. Ratings are updated match by match through a weighted moving average, so recent performances have greater influence while earlier performances remain part of the player's profile.

## Batters
Each innings considers:
- runs and scoring volume
- strike rate
- match scoring environment
- ratings of bowlers faced
- ratings of bowlers against whom runs were scored
- not-out status
- team result
- opponent team strength
- knockout context
- sample-size dampening for newer players

## Bowlers
Each spell considers:
- official wickets only
- economy and runs conceded
- workload
- match scoring environment
- ratings of dismissed batters
- opposition batting strength
- team result
- opponent team strength
- knockout context
- sample-size dampening for newer players

## All-rounders
Batting and bowling ratings are combined using the ICC-style multiplicative index:

batting rating × bowling rating / 1000

Both disciplines require a minimum workload before a player is shown.

## Teams
Team ratings use match outcome against the relative pre-match rating of the opponent, with a modest margin adjustment and extra knockout context.

## Knockout inference
The current database schema does not store playoff stage labels. For seasons containing a full IPL-sized schedule, the final four chronological matches are treated as knockout matches for contextual weighting.

## Franchise identity and season groups
Historical internal team names are canonicalized before the ranking engine updates ratings. Royal Challengers Bangalore and Royal Challengers Bengaluru, Delhi Daredevils and Delhi Capitals, and Kings XI Punjab and Punjab Kings are therefore treated as one franchise and displayed using the latest franchise name used by the application.

The season control also supports any group of seasons. When a group is selected, only matches from those seasons are processed chronologically and the rating history is calculated across that selected set, rather than simply adding separate season tables together.



## Team Championship Context
For every selected IPL season, the engine identifies the last chronological match of that year as the season final and treats its winner as the IPL champion. The champion receives a +24 title-context bonus to the team rating after the final. The team leaderboard replaces Recent Form with a 🏆 Titles Won column and shows the number of championships earned within the selected season set.


## Era and Season Environment Adjustment

All cross-season rankings are normalized to the scoring environment of each selected IPL season. The engine calculates season baselines for runs per ball, batting average, innings score, bowling economy and wickets per ball. Batters are evaluated relative to the season strike-rate and volume environment; bowlers are evaluated relative to season economy and wicket-taking rates. Team batting and bowling ratings blend player quality with team scoring/defensive performance relative to the same season baseline. This prevents earlier low-scoring eras from being penalized against modern high-scoring seasons. Match, opposition, knockout and title context remain additional layers rather than being replaced by normalization.

## Continuous Rating History and Season-End Snapshots

The ranking engine now processes IPL matches chronologically from the first available season and carries player and team ratings forward across seasons. Ratings are not reset when a season filter is selected.

- A single-season selection shows the rating snapshot at the end of that season.
- A multi-season selection shows the rating snapshot at the end of the latest selected season.
- All Seasons shows the latest available completed-season snapshot.
- Team rankings follow the same continuous history and snapshot model.
- Team filters do not alter the underlying league-wide rating environment or renumber the rating universe.

This ensures that a player who debuted in 2025 has the same 2025 end-of-season rating whether viewed through the 2025 filter or through a later historical calculation. The latest All Seasons rating represents the player's accumulated rating at the latest snapshot.

## Display Eligibility Anchor Rule
For player rankings, rating calculation and display eligibility are separate. Ratings always use the continuous historical rating timeline up to the selected snapshot. To appear in a filtered ranking, however, a player must have played at least one match in the anchor season: any selected season for a specific or multi-season selection, and the latest completed season for All Seasons. This prevents players who entered only after the beginning of the selected ranking period from appearing in that period's leaderboard, while preserving their continuous rating history.
