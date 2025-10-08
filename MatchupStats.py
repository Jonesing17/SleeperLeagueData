# -*- coding: utf-8 -*-
"""
Created on Fri Sep 12 18:41:21 2025

@author: kjone
"""
import pandas

def basicStats(leagueMatchups):
    differentials = leagueMatchups.Points - leagueMatchups.OpponentPoints
    leagueMatchups['ScoreDifferential'] = differentials
    results = differentials > 0
    scoreResult = ['W' if result else 'L' for result in results]
    leagueMatchups['Result'] = scoreResult
    
    return leagueMatchups


def standings(leagueMatchups, leagueRoster):
    wins = []
    loses = []
    
    pointsFor = []
    pointsAgainst = []
    
    for rosters in range(1, len(leagueRoster)+1):
        
        wins.append(len(leagueMatchups.query("RosterID == "+str(rosters)+" and Result == 'W'")))
        loses.append(len(leagueMatchups.query("RosterID == "+str(rosters)+" and Result == 'L'")))
        pointsFor.append(sum(map(float, leagueMatchups.query("RosterID == "+str(rosters)).Points)))    
        pointsAgainst.append(sum(map(float, leagueMatchups.query("RosterID == "+str(rosters)).OpponentPoints)))
    
    
    leagueRoster['Wins'] = wins
    leagueRoster['Loses'] = loses
    leagueRoster['PF'] = pointsFor
    leagueRoster['PA'] = pointsAgainst
    
    leagueRoster = leagueRoster.sort_values(by = ['Wins', 'PF'], ascending = [False, False])

    return leagueRoster