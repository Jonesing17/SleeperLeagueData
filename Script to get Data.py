# -*- coding: utf-8 -*-
"""
Created on Fri Sep  5 21:06:26 2025

@author: kjone
"""

import ImportSleeperData as sleeper
import MatchupStats as ms

#import pandas


"""
Enter a username

Enter the years that you want

Get all leagues for that year

Ask which of those leagues that you want to retrieve'

Retrieve 


"""

username = input("Enter your username: ") 
userID = sleeper.getUserID(username= username)

multipleYears = ''
while True:
    multipleYears = input("Would you like to input multiple years(Y/N): ").strip().upper()
    if multipleYears in ['Y', 'N']:
        break
    else:
        print("Invalid input. Try again.")



startYear = 0
endYear = 0
isInt = False

if multipleYears == "Y":

    while isInt == False:
        startYear = input("What is the first year you'd like to retrieve? (4-digit year) :")
    
        try:
            if(isinstance(int(startYear), int) and len(startYear) == 4):
                isInt = True
                startYear = int(startYear)
        except:
            print("Value entered isn't a valid year: "+startYear)
                
    isInt = False
    while isInt == False:        
        endYear = input("What is the last year you'd like to retrieve? (4-digit year) :")
    
        try:
            if(isinstance(int(endYear), int) and len(endYear) == 4):
                isInt = True
                endYear = int(endYear)
        except:
            print("Value entered isn't a valid year: "+endYear)            
else:
    
    while isInt == False:
        startYear = input("What year would you like to retrieve? (4-digit year) :")
 
        try:
            if(isinstance(int(startYear), int) and len(startYear) == 4):
                isInt = True
                startYear = int(startYear)
        except:
            print("Value entered isn't a valid year: "+startYear)

del isInt   #no longer need isInt


#TODO any thresholds on years?

if endYear == 0:
    years = [startYear]    
else:
    if (startYear > endYear):
        tempYear = startYear
        startYear = endYear
        endYear = tempYear
        del tempYear
    years = list(range(startYear, endYear+1))

del startYear #no longer need startYear 
del endYear #no longer need endYear  
del multipleYears

print(years)

week = 0


#TODO
startWeek = 1 
##endWeek = playoff_week_start -1

for year in years:
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





