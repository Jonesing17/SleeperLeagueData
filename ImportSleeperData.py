# -*- coding: utf-8 -*-
"""
Created on Fri Sep  5 19:14:12 2025

@author: kjone
"""

import requests
import pandas



#get UserID 
##TODO prompting for username rather if username isn't specied
def getUserID(username = ""):
    
    if username == "":
        username = input("Enter your username: ")
        
    response = requests.get("https://api.sleeper.app/v1/user/"+username)
    #if successful return the userID
    if ((response.status_code == 200) & (response.content != b'null')):
        userID = response.json()["user_id"]
        return (userID)
        
    else:
        raise SystemExit("Error: "+username+" is not a valid username")
        


##get a list of Leagues
##TODO change default of 2024 to prompt if empty
##TODO a prompt within this function to return the league you want
def getLeagueIDs(userID, year = ""):
    
    if year == "":
        year = input("Enter year: ")

    response = requests.get("https://api.sleeper.app/v1/user/"+userID+"/leagues/nfl/"+str(year)+"/")    
    if ((response.status_code == 200)):
        leagueID = []
        leagues = response.json()
        for i in range(len(leagues)):
            leagueID.append(leagues[i]["league_id"]) 
        return (pandas.DataFrame({"LeagueID": leagueID}))

    else:
        print("Exception occured: response is "+ response. statuscode)
        return "NULL"
        

def getLeagueNames(leagueIDs):
    
    ##leagueNames =numpy.empty(shape = 0, dtype = str, order = 'F')
    leagueNames = []
    leagueYears = []
    for i in range(0, len(leagueIDs)):
        response = requests.get("https://api.sleeper.app/v1/league/"+leagueIDs.loc[i, 'LeagueID'])    
        if response.status_code == 200:
            ##leagueNames = numpy.append(leagueNames, response.json()["name"])
            leagueNames.append(response.json()["name"])
            leagueYears.append(response.json()["season"])
        else:
            print("Exception occured: response is "+ response. statuscode)
            return "NULL"

    leagueIDs ["LeagueName"] = leagueNames
    leagueIDs ["LeagueYear"] = leagueYears
    
    return  leagueIDs

def buildLeagueRoster(leagueID):
    rosterID = []
    rosterName = []
    
    
    response = requests.get("https://api.sleeper.app/v1/league/"+leagueID+"/users")
    #if successful return the roster
    if ((response.status_code == 200) & (response.content != b'null')):
        for i in range(0,len(response.json())):
            rosterID.append(i+1)
            rosterName.append(response.json()[i]['display_name'])
    else:
        raise SystemExit("Unspecified Error: buildLeagueRoster")
    
    return pandas.DataFrame({"RosterID": rosterID, "RosterName": rosterName})                 
                                 
def buildLeagueMatchups(leagueID, week = 0):
    
    weeks = []
    rosterID = []
    points = []
    matchupID = []
    
    start_week = week
    if week == 0:
        start_week = 1
        week = 14  #TODO - Assume 14 week regular season 
    
    
    for week in range(start_week, week+1):
        response = requests.get("https://api.sleeper.app/v1/league/"+leagueID+"/matchups/"+ str(week))
        matchups = response.json()
        #if successful return the roster
        if ((response.status_code == 200) & (response.content != b'null')):
            for playerID in range(0,len(matchups)):
                
                weeks.append(week)
                rosterID.append(matchups[playerID]['roster_id'])
                points.append(matchups[playerID]['points'])
                matchupID.append(matchups[playerID]['matchup_id'])
            
        else:
            raise SystemExit("Unspecified Error: buildLeagueRoster")
    #year = 
    matchups = pandas.DataFrame({"Week": weeks, "MatchupID": matchupID, "RosterID": rosterID, "Points": points})
    
    
    return matchups              

def pairOffMatchups(leagueMatchups, leagueRoster):  
    
    opponentIDs = []
    opponentPoints = []
    teamNames = []
    opponentNames = []
    
    for matchup in range (len(leagueMatchups)):
     
        teamID = leagueMatchups['RosterID'][matchup]
        matchupID = leagueMatchups['MatchupID'][matchup]
        week = leagueMatchups['Week'][matchup]
        teamNames.append(leagueRoster.query("RosterID == "+str(teamID)).RosterName[:].item())
        
        opponentID = leagueMatchups.query("Week == "+str(week)+" and MatchupID == "+str(matchupID)+" and RosterID != "+str(teamID)).RosterID.item()
        opponentIDs.append(opponentID)
        opponentNames.append(leagueRoster.query("RosterID == "+str(opponentID)).RosterName[:].item())
        opponentPoints.append(leagueMatchups.query("Week == "+str(week)+" and MatchupID == "+str(matchupID)+" and RosterID != "+str(teamID)).Points.item())
    #TEMPleagueMatchups = leagueMatchups.copy(deep = True)
    leagueMatchups ['TeamName'] = teamNames
    leagueMatchups ['OpponentID'] = opponentIDs
    leagueMatchups ['OpponentNames'] = opponentNames
    leagueMatchups ['OpponentPoints'] = opponentPoints
    
    return leagueMatchups
                                