### Navigation
Turn-by-turn navigation was extensively tested in real-world driving and walking conditions, yielding the following findings:
1. We don't currently have any route update or deviation detection logic like Google Maps does.
Scenario: user defines GPS position of their device as start point, looks up endpoint. While en route to the same endpoint, takes a slightly different route by making an unexpected turn compared to calculated route.
Actual behavior: route does not update--although interestingly, turn-by-turn seems to attempt to keep directing them back to the route--and user is required to completely exit navigation, recalculate the route, then re-enter navigation for minor deviation updates.
Desired behavior: route can detect deviations and intelligently update both the path and turn-by-turn navigation automatically.
2. We don't debounce turn-by-turn voice updates. Voice updates can trigger many times in succession when circling or exiting a parking lot or when approaching a turn, which is extremely annoying and sounds very buggy. My observation is that we probably trigger turn-by-turn voie routing events based on a fixed radius from the next turn at a given speed, and these can either overlap of not set correctly for reducing speed as a user drives towards an approaching turn, or trigger many times as a user navigates a parking lot, roundabout, or other road feature approaching the next turn.
3. Navigation icon should be locked towards the bottom of the screen so the user can see the upcoming road ahead and prepare accordingly. Icon is currently locked in the center of the screen, which is not nearly as useful. It's not even the actual center since we aren't taking the top navigation pane into account. We need to account for that, then also lock the navigation icon towards the bottom of the screen--like Google Maps. I know I mention emulating how they do it often, but they are the standard.
4. Side bar hamburger and voice toggle overlap the top navigation pane on mobile. We've tried to solve this before, and this is either regression or we never solved it successfully. They should just be locked to below (not z layer below, but lower than on screen) the top navigation pane on the screen.
5. We don't appear to have a "return to north" icon/button present on desktop or mobile anymore. We used to, so this is regression. Review commits to determine whether this was removed in error or unintentionally while fixing other bugs. If the latter, we need to update pitfalls.md once the fix is identified.

### Setup
I had a beta tester attempt setup and they ran into a number of problems. Setup was ultimately unsuccessful as a result.
1. We had planned to allow users to define custom storage paths, but this option was simply missing. Not only do they need to be able to define the storage device, they need to be able to define the full path on that device. We should allow this with both a GUI picker and simple path entry in a field.
2. When they tried to do a basic scraper imagery download in a reference Pi running the latest Trixie Raspbian build, they received the error: 127.0.0.1:57066 - "GET /ws/progress HTTP/1.1" 404 not found
Unsupported upgrade request
No supported WebSoket library detected. Please use "pip install 'uvicorn[standard]'", or install 'websockets' or 'wsproto' manually.
This appears to be a missing dependency which we did not check for. As a result:
--We need to determine why this dependency was missing and address it.
--We need to determine why this dependency was uncaught in LXD container testing.
--We need to verify other dependencies are not experiencing the same issue but remain uncaught.
3. We did not handle that error gracefully. Pipeline simply remained at 0% while errors dumped to and filled console. We need better error handling.