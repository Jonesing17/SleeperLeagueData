# -*- coding: utf-8 -*-
"""
Created on Fri Sep  5 21:06:26 2025

@author: kjone
"""

import ImportSleeperData as sleeper
import MatchupStats as ms

#import pandas


"""
From username
Get all leagues for that year
Hardcoded to get the league ID for Rock Bottom 
CONSIDER: Pick the league you want 
"""
###

##TODO - Remove comment so it requests a username
username = input("Enter your username: ") 
userID = sleeper.getUserID(username= username)

multipleYears = ''
while True:
    multipleYears = input("Would you like to input multiple years(Y/N): ").strip().upper()
    if multipleYears in ['Y', 'N']:
        break
    else:
        print("Invalid input. Try again.")


Years = []
if multipleYears == "Y":
    startYear = input("What is the first year you'd like to receive? (4-digit year) :")

    if (len(start ==4) and int())

year = "2024"
week = 0

##CONSIDER if userID is invalid, throw exceptions  


userLeagues = sleeper.getLeagueIDs(userID, year = year)

if (len(userLeagues)<=0):
    raise SystemExit("Error: No Valid Leagues.")

userLeagues = sleeper.getLeagueNames(leagueIDs = userLeagues)

userLeagueRow = 1

##TODO - Present options for league
##TODO - Request what league - Loop until valid
for i in range(0, len(userLeagues)):
    if(userLeagues.loc[i][1] == "Rock Bottom"):
        userLeagueRow = i
del i


"""
Using userLeagueRow and userLeague
Build the roster for that league, in that year
"""
leagueRoster = sleeper.buildLeagueRoster(leagueID = userLeagues.loc[userLeagueRow][0]) 

"""
Using userLeagueRow and userLeague
Build the schedule for that league, in that year
"""


leagueMatchups = sleeper.buildLeagueMatchups(leagueID = userLeagues.loc[userLeagueRow][0], week = week)
leagueMatchups.insert(0, "Year", [year]*len(leagueMatchups))
        


leagueMatchups = sleeper.pairOffMatchups(leagueMatchups, leagueRoster)

leagueMatchups = ms.basicStats(leagueMatchups)
leagueStandings = ms.standings(leagueMatchups, leagueRoster)



"""
Using userLeagueRow and userLeague
Build the transactions for that league, in that year
"""


"""
Using userLeagueRow and userLeague
Build the player output for that league, in that year
"""








##TODO build a choice rather than hardcoding
##primaryLeagueID = userLeagues2['RockBottom'][0]

##leagueRoster =
##getLeagueInfo





