import networkx as nx
import os
from py2neo import Graph
import matplotlib.pyplot as plt
import matplotlib.patches
import random
from datetime import datetime
import pandas as pd
from scipy import spatial
import csv
import numpy as np

from flask import Blueprint

simulator = Blueprint('simulator', __name__)
# gdb = GraphDatabase(os.environ.get("GRAPHENEDB_URL"))
graphurl = "http://app52089542-qMnWmY:PTPE2ka4DyL8PxESRfuR@app52089542qmnwmy.sb05.stations.graphenedb.com:24789"
py2neograph = Graph(graphurl)


# py2neograph = Graph(os.environ.get("GRAPHENEDB_URL"))

@simulator.route('/api/runModel', methods=['GET', 'POST'])
class GraphingAgent():
    def __init__(self, random=True):
        self.intitsomething = []
        self.orig_gamma = .5
        self.orig_alpha = .75
        self.gamma, self.alpha = self.orig_gamma, self.orig_alpha
        self.orig_q_value = 3
        self.allactions = {"connect", "removenode", "disconnect"}
        self.states = []
        self.state = None
        self.info = []
        self.q = dict()
        self.orig_epsilon = .1
        self.epsilon = self.orig_epsilon
        self.old_graph_Stats, self.old_state, self.old_action, self.old_reward = None, None, None, 0
        self.saveGraphStats = {
            "iter": [],
            "radius": [],
            "density": [],
            "avgcluscoeff": [],
            "nodeconnectivity": [],
            "components": [],
            "avgpathlength": [],
            "reward": [],
            "nodecount": []
        }
        self.random = random
        self.alltags = range(0, 100, 1)
        self.qualitystats = {}

    def main(self, repeat, growrate, matchrate):
        # repeat = number of times to iterate throuhg // the number of days a moderator would work through
        # growrate = number of users added per day
        # matchrate = number of matches to consider
        # epsilon - used in the q value function
        # gamma = used in q value function

        # tagGraphObj, yserCount = getNodesFromDB(tagsq, nodecountq)
        # procTags = processNodes(tagGraphObj)
        # tagsq = " MATCH (x:User)-[*..2]-(y:Tag) RETURN id(x) as id, COLLECT(id(y)) as rels, count(y) as endcount LIMIT 5"
        # tagsq = " MATCH (x:User)-[*..2]-(y:User) RETURN id(x) as id, COLLECT(id(y)) as rels, count(y) as endcount LIMIT 5"
        # This is for the comparison data to current DB state
        # Cypher query that gets the users in a graph and their connection
        graphq = " MATCH (x:User)-[*..2]-(y:User) MATCH (m:Message)-[]-(x:User) RETURN id(x) as id, COLLECT(id(y)) as rels, count(y) as endcount, count(m) as mcount LIMIT 20"

        # Cyper query that gets the number of nodes in the graph
        nodecountq = "MATCH (x) RETURN count(x) as count LIMIT 1"

        # # Returned graph objects
        seqGraphObj, startCount = self.getNodesFromDB(graphq, nodecountq)
        processFromDB, nodestatsDB = self.processNodes(seqGraphObj)

        fromDBgraphstats = self.updateGraphStats(nx.Graph(processFromDB))

        dBStats = {
            "nodeStats": nodestatsDB,
            "graphStats": fromDBgraphstats
        }
        # dbGraph = nx.Graph(processFromDB)
        x = pd.DataFrame(dBStats)

        # # Saves initial stats to a csv and json
        # x.to_csv("intialnodedata.csv")
        # x.to_json("initialdatajson.json")

        # Uncomment to visualize the graph community from the BioBreaks graph database
        # nx.draw(dbGraph, with_labels=True, font_color='w')
        # plt.show()

        # Generate perfect starting seed community of 5 people
        procNodes = {
            0: [1, 2, 3, 4],
            1: [2, 3, 4, 0],
            2: [3, 4, 0, 1],
            3: [4, 0, 1, 2],
            4: [0, 1, 2, 3]
        }
        startnodenum = len(procNodes)
        origin = repeat

        # Interactive graphing
        plt.ion()

        # TODO: Initialize variables
        counter = 0

        # for the initial graph stats and visualization
        # stats = self.updateGraphStats(initgraph)
        # nx.draw(initgraph)
        # plt.show()

        # Useful for saving data
        savestring = "Figures/"
        time = datetime.now().strftime("%Y-%m-%d%H.%M")
        updatedGraph = None

        # While we still have repetitions to go through
        while repeat > 0:
            # print "# of states", len(self.states), "Q: ", len(self.q), self.q
            # TODO: GET INPUTS, graphStats, matches
            #  update graph on repeat increase, except for initialization using procNodes
            if repeat == origin:
                updatedGraph = self.updateStats(procNodes, [])
            else:
                updatedGraph = self.updateStats([], updatedGraph)

            # updates the graph statistics for the network
            graphStats = self.updateGraphStats(updatedGraph)
            # creates new nodes based on the growrate
            updatedGraph, newnodes = self.addandConnect(updatedGraph, startnodenum, growrate)

            # Returns the matches for new nodes and internal nodes
            matches, newmatches = self.suggestMatches(updatedGraph, graphStats, matchrate, newnodes)

            # TODO: UPDATE STATE
            graphStats = self.normalizeStats(graphStats)
            temp = graphStats
            if self.old_graph_Stats != None:
                #### UNCOMMENT THIS TO GET DISCRETIZED DATA
                # for attribute in graphStats:
                #     if graphStats[attribute] > self.old_graph_Stats[attribute]:
                #         temp[attribute] = 1
                #     if graphStats[attribute] < self.old_graph_Stats[attribute]:
                #         temp[attribute] = -1
                #     if graphStats[attribute] == self.old_graph_Stats[attribute]:
                #         temp[attribute] = 0
                # print "compare", attribute, graphStats[attribute], self.old_graph_Stats[attribute], graphStats[attribute]
                self.state = (temp, self.old_action)
            else:
                for attribute in graphStats:
                    graphStats[attribute] = 0
                self.state = (graphStats, self.old_action)

            if self.state not in self.states and self.state != None:
                self.states.append(self.state)
                index = self.states.index(self.state)
                self.q[index] = dict({
                    None: self.orig_q_value,
                    "connect": self.orig_q_value,
                    "disconnect": self.orig_q_value,
                    "removenode": self.orig_q_value})

            # print "HERE:", self.q, self.state, self.states
            if counter > 0:
                self.update_q(self.old_state, self.old_action, self.old_reward, self.state)
            else:
                # print trialnumber
                self.info.append({'penalty': [], 'reward': [], 'net reward': 0})

            # TODO: Select action according to policy
            action = self.determineUtility(matches, self.state)

            # TODO: Execute action and get reward
            updatedGraph, reward = self.takeAction(action, updatedGraph, newmatches)

            # TODO: Learn policy based on state, action, and reward.

            # Growth rate is applied

            self.old_graph_Stats = graphStats
            # print "oldgraphstats", self.old_graph_Stats
            for key, index in enumerate(self.saveGraphStats):
                if index != 'iter' and index != 'reward':
                    self.saveGraphStats[index].append(self.old_graph_Stats[index])
            self.saveGraphStats['iter'].append(counter)
            self.saveGraphStats['reward'].append(reward)

            self.old_reward = reward
            self.old_action = action
            self.old_state = self.state

            startnodenum += growrate
            repeat -= 1
            counter += 1

            print len(updatedGraph.nodes()), counter, repeat
            # Plot and stuff and save it to the file for gif creation later --- UNDO BELOW
            nx.draw(updatedGraph, with_labels=True, font_color='w')
            plt.show()
            pop = savestring + time + str(origin - repeat) + ".png"
            # plt.savefig(pop)
            plt.pause(.005)
            if repeat != 0:
                plt.clf()  # Plot and stuff and save it to the file for gif creation later --- UNDO BELOW

        plt.figure()
        # print self.saveGraphStats
        ax = plt.subplot(321)
        ax.set_title("Avg Path Length")
        ax.plot(self.saveGraphStats['iter'], self.saveGraphStats['avgpathlength'], 'ro')
        ax = plt.subplot(322)
        ax.set_title("Avg Clus Coeff")
        ax.plot(self.saveGraphStats['iter'], self.saveGraphStats['avgcluscoeff'], 'go')
        ax = plt.subplot(323)
        rewardtext = "Cumulative Reward: " + str(sum(self.saveGraphStats['reward']))
        ax.set_title(rewardtext)
        ax.plot(self.saveGraphStats['iter'], self.saveGraphStats['reward'], 'bo')
        ax = plt.subplot(324)
        ax.set_title("Degree Distribution")
        d = nx.degree(updatedGraph)
        ax.hist(d.values())
        ax = plt.subplot(325)
        ax.set_title("Centrality")
        centralrray = []
        boom = nx.get_node_attributes(updatedGraph, 'stats')
        for x in boom:
            centralrray.append(boom[x]['centrality'])
        ax.plot([i for i in range(len(centralrray))], centralrray, 'mo')
        ax = plt.subplot(326)
        title = "Number of Nodes +" + str(growrate)
        ax.set_title(title)
        ax.plot(self.saveGraphStats['iter'], self.saveGraphStats['nodecount'], 'co')
        plt.show()

        plt.figure()
        node_order = None
        adjacency_matrix = nx.to_numpy_matrix(updatedGraph, dtype=np.bool, nodelist=node_order)
        plt.imshow(adjacency_matrix,
                   cmap="Reds",
                   interpolation="none")
        plt.colorbar()
        plt.title('Network Heatmap')

        plt.figure()
        title = "User Match closeness, " + str(len(self.qualitystats)) + " matches, " + str(len(updatedGraph.nodes())) + " users"
        plt.title(title)
        nodestats = nx.get_node_attributes(updatedGraph, 'stats')
        noderay = {}
        for node in nodestats:
            noderay[node] = nodestats[node]['userscore']
        plt.hist(self.qualitystats.values())
        plt.show()

        # print updatedGraph.order(), updatedGraph.size(), updatedGraph.nodes(data=True)
        # print graphStats

        return self.old_graph_Stats

    def addandConnect(self, graph, startnum, growrate):
        addednodes = []
        for i in range(startnum, startnum + growrate):
            x = User(i, self.random)
            graph.add_node(i, probability=x.probability, msgrate=x.msgrate, tags=x.tags)
            addednodes.append(i)

        return graph, addednodes

    def normalizeStats(self, graphStats):

        return graphStats

    def removeDupes(self, list):
        newlist = []
        for item in list:
            if item not in newlist:
                newlist.append(item)

        return newlist

    # Get all nodes
    def getNodesFromDB(self, graphq, nodecount):
        # graphq = " MATCH (m:Message)-[]-(x:User)-[*..3]-(y:User) RETURN id(x),COLLECT(id(y)), COUNT(m) LIMIT 5"
        seqGraphObj = py2neograph.run(graphq).data()
        startCount = py2neograph.run(nodecount).data()
        return seqGraphObj, startCount

    # turn it into graph matrix
    def processNodes(self, nodes):
        redata = {}
        start = 0
        stats = {}
        for key, node in enumerate(nodes):
            # print key,node
            # redata[node['id']] = removeDupes(node['rels'])
            redata[node['id']] = self.removeDupes(node['rels'])
            stats[node['id']] = {
                "relcount": len(node['rels']),
                "msgcount": node['mcount'],
                "endcount": node['endcount']
            }
            start += 1

        return redata, stats

    # update individual nodes stats
    def updateStats(self, firstnodes, oldgraph):
        # for each node update it's stats
        if firstnodes != []:
            graph = nx.Graph(firstnodes)
            nodes = graph.nodes()
            for it in nodes:
                graph.node[it]['tags'] = random.sample(self.alltags, 3)
                graph.node[it]['probability'] = np.random.power(1)
        else:
            graph = oldgraph

        centralities = nx.degree_centrality(graph)
        betweenness = nx.betweenness_centrality(graph)
        eigenvectors = nx.betweenness_centrality(graph)
        closenesscentrality = nx.closeness_centrality(graph)
        degrees = nx.degree(graph)
        rgcentralities = self.checkzero(max(centralities.values()) - min(centralities.values()))
        rgbetweeness = self.checkzero(max(betweenness.values()) - min(betweenness.values()))
        rgeigenvectors = self.checkzero(max(eigenvectors.values()) - min(eigenvectors.values()))
        rgclosesness = self.checkzero(max(closenesscentrality.values()) - min(closenesscentrality.values()))
        rgdegrees = self.checkzero(max(degrees.values()) - min(degrees.values()))

        # print "AVERAGES", rgbetweeness, rgcentralities, rgclosesness, rgdegrees, rgeigenvectors
        for key, node in enumerate(graph.nodes()):
            graph.node[node]['stats'] = {
                "msg/day": key, "centrality": centralities[node] / rgcentralities,
                "betweeness": betweenness[node] / rgbetweeness,
                "closeness": closenesscentrality[node] / rgclosesness,
                "eigenvector": eigenvectors[node] / rgeigenvectors,
                "userscore": sum([centralities[node] / rgcentralities, betweenness[node] / rgbetweeness,
                                  closenesscentrality[node] / rgclosesness, eigenvectors[node] / rgeigenvectors]),
                "degree": degrees[node] / rgdegrees
            }
            # graph.node[node['id']]
            # Tags,
        return graph

    # update the networknx.degree_centrality(g) stats
    def checkzero(self, number):
        if number == 0:
            return 1
        else:
            return number

    # update full Graph Stats
    def updateGraphStats(self, graph):

        origgraph = graph
        if nx.is_connected(graph):
            random = 0
        else:
            connectedcomp = nx.connected_component_subgraphs(graph)
            graph = max(connectedcomp)

        if len(graph) > 1:
            pathlength = nx.average_shortest_path_length(graph)
        else:
            pathlength = 0

        # print graph.nodes(), len(graph), nx.is_connected(graph)

        stats = {
            "radius": nx.radius(graph),
            "density": nx.density(graph),
            "nodecount": len(graph.nodes()),
            "center": nx.center(graph),
            "avgcluscoeff": nx.average_clustering(graph),
            "nodeconnectivity": nx.node_connectivity(graph),
            "components": nx.number_connected_components(graph),
            "avgpathlength": pathlength
        }

        # print "updated graph stats", stats
        return stats

    def update_q(self, oldstate, actionlist, reward, newstate):
        qMax = self.maxqs(newstate)
        oldindex = self.states.index(oldstate)

        for action in actionlist:
            action = action[0]
            # print "in updateq", self.q[oldindex][action], action
            if oldstate in self.states and self.q[oldindex][action] is not None:
                self.q[oldindex][action] += self.alpha * (reward + self.gamma * qMax - self.q[oldindex][action])
            else:
                self.states.append(oldstate)
                self.q[oldindex][action] = reward

    def maxqs(self, state):

        if state in self.states:
            index = self.states.index(state)
            qmax = max(self.q[index].values())
        else:
            qmax = self.orig_q_value
            # print "in maxqs", qmax, states, state, state in states

        return qmax

    # Recommend top 5
    ### identify biggest network holes
    ### identify most similar among the network hole matches
    ### score matches based on combined hole + tags + links/channel mentions + stats
    def suggestMatches(self, graph, graphstats, matchrate, newnodes):
        nodes = graph.nodes()

        suggs = []
        newsuggs = []
        removenew = list(set(nodes) - set(newnodes))
        for node in newnodes:
            if len(nodes) > 1:
                if self.random:
                    friend = random.sample(removenew, 1)
                else:
                    friend = self.matchNode(node, graph, removenew)
                # print graph.node[node]
                specprob = graph.node[node]['probability'] + graph.node[friend[0]]['probability']
                # print friend, node, removenew
                newsuggs.append(("connect", (node, friend[0], specprob)))  # DOING THE MOST RIGHT HERE

        while matchrate > 0:
            a = random.sample(removenew, 1)
            if self.random:
                b = random.sample(removenew, 1)
                if b == a:
                    b = random.sample(removenew, 1)
            else:
                b = self.matchNode(a[0], graph, removenew)
                if b == a:
                    b = random.sample(removenew, 1)
            prob = graph.node[a[0]]['probability'] + graph.node[b[0]]['probability']
            suggs.append((a[0], b[0], prob))
            matchrate -= 1

        # print "suggested matches", suggs, len(nodes)
        return suggs, newsuggs

    def findNodeSimilarity(self, node_a, node_b, graph):
        close = 1 - spatial.distance.cosine(graph.node[node_a]["tags"], graph.node[node_b]["tags"])
        # userdifference = abs(graph.node[node_a]['stats']['userscore'] - graph.node[node_b]['stats']['userscore'])
        qualitytext = str(node_a) + str(node_b)
        self.qualitystats[qualitytext] = close
        return

    def matchNode(self, node, graph, removenew):
        matchnode = node
        matchray = {}
        allnodes = removenew
        # Check if nodes have same tags
        for option, key in enumerate(allnodes):
            close = 1 - spatial.distance.cosine(graph.node[node]["tags"], graph.node[option]["tags"])
            matchray[option] = {"spdist": close, "userscore": graph.node[option]['stats']['userscore']}
            if key > len(allnodes):
                break
        # print "MATCHRAYS", matchray
        # Check if nodes have high degree amongst tags
        sorted_matchray = sorted(matchray.items(), key=lambda x: (x[1]['spdist'], x[1]['userscore']))
        sorted_matchray.reverse()
        # print "inside matchnodes", len(allnodes),  sorted_matchray
        if len(sorted_matchray) > 0:
            matchnode = random.sample(sorted_matchray[:5], 1)[0]
            # matchnode= sorted_matchray[0]
            # print "matchnode+ray" , matchnode, sorted_matchray
        inray = [matchnode[0]]
        # print "length of sorted matchray", len(sorted_matchray)
        # randomly connect if not already connected

        return inray

    # Select match based on utility function
    def determineUtility(self, matches, state):
        actionpairs = []
        allactions = self.allactions

        if state in self.states and random.random() > self.epsilon:
            stateindex = self.states.index(state)
            # print "MAX", max(self.q[stateindex].values())
            allactions = [action for action, q in self.q[stateindex].iteritems()
                          if q == max(self.q[stateindex].values())]
            # print "chose action", state, self.q, self.q[stateindex], max(self.q[stateindex].values()), allactions

            # for action, q in self.q[stateindex].iteritems():
            #     print action, q
        # print "determining Utility", allactions, state
        if self.random:
            action = random.sample(allactions, 1)
        else:
            # action = ["connect"]
            action = random.sample(allactions, 1)
        for match in matches:
            actionpairs.append((action[0], match))

        # print "utility determined, action + match: ", actionpairs
        return actionpairs

    # Complete action
    ### Update graph matrix
    ### Increase node messages/connections
    ### Assign reward
    def takeAction(self, actionpairs, graph, specpairs):
        reward = 0
        actionpairs = actionpairs + specpairs

        for action in actionpairs:
            # print "chose action", action
            if action[0] == "removenode":
                chose = random.sample(action[1][:1], 1)
                if graph.has_node(chose):
                    graph.remove_node(chose)
                reward += -10
            if action[0] == "connect":
                # print action
                graph.add_edge(action[1][0], action[1][1], weight=action[1][2])
                self.findNodeSimilarity(action[1][0], action[1][1], graph)
                reward += +10
            if action[0] == "disconnect":
                if graph.has_edge(action[1][0], action[1][1]):
                    graph.remove_edge(action[1][0], action[1][1])
                    reward += -4
            if action[0] == None:
                reward += -1

        reward = reward - len(specpairs) * 10

        # print "took actions", actionpairs, reward
        return graph, reward


class User():
    def __init__(self, id, random):
        self.id = id
        self.tags = self.selectTags([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        self.msgrate = np.random.power(1)
        self.probability = .5
        self.random = random
        self.updateUser()

    def selectTags(self, tagslist):
        selectedTags = random.sample(tagslist, 3)
        return selectedTags

    def updateUser(self):
        if self.random:
            self.probability = random.random()
        else:
            self.probability = np.random.power(1)


def experiment():
    repeatrange = (2, 21, 2)
    growraterange = (2, 10, 1)
    matchraterange = (2, 10, 1)

    modelAgent = GraphingAgent(random=False)
    randomAgent = GraphingAgent(random=True)

    repeatresults = {"Model": [], "Random": []}
    growrateresults = {"Model": [], "Random": []}
    matchrateresults = {"Model": [], "Random": []}
    baserepeat = 20
    basegrow = 2
    basematch = 5

    rand = []
    model = []
    ra = None
    for i in range(repeatrange[0], repeatrange[1], repeatrange[2]):
        print i, "repeat random"
        ra = randomAgent.main(i, basegrow, basematch)
        print i, "repeat model"
        mo = modelAgent.main(i, basegrow, basematch)
        ra['model'] = "random"
        ra['repeat'] = i
        ra['growthrate'] = basegrow
        ra['matchrate'] = basematch
        mo['model'] = "model"
        mo['repeat'] = i
        mo['growthrate'] = basegrow
        mo['matchrate'] = basematch
        repeatresults["Random"].append(ra)
        repeatresults["Model"].append(mo)

    keys = ra.keys()
    print keys

    for i in range(growraterange[0], growraterange[1], growraterange[2]):
        print i, "growrate random"
        ra = randomAgent.main(10, i, basematch)
        print i, "growrate model"
        mo = modelAgent.main(10, i, basematch)
        ra['model'] = "random"
        ra['repeat'] = baserepeat
        ra['growthrate'] = i
        ra['matchrate'] = basematch
        mo['model'] = "model"
        mo['repeat'] = baserepeat
        mo['growthrate'] = i
        mo['matchrate'] = basematch

        growrateresults["Random"].append(ra)
        growrateresults["Model"].append(mo)

    for i in range(matchraterange[0], matchraterange[1], matchraterange[2]):
        print i, "matchrate random"
        ra = randomAgent.main(10, 2, i)
        print i, "matchrate model"
        mo = modelAgent.main(10, 2, i)

        ra['model'] = "random"
        ra['repeat'] = baserepeat
        ra['growthrate'] = basegrow
        ra['matchrate'] = i
        mo['model'] = "model"
        mo['repeat'] = baserepeat
        mo['growthrate'] = basegrow
        mo['matchrate'] = i
        matchrateresults["Random"].append(ra)
        matchrateresults["Model"].append(mo)

    print "writing to csv"
    with open("graphStats.csv", "wb") as f:
        writer = csv.DictWriter(f, keys)
        writer.writeheader()
        writer.writerows(repeatresults['Random'])
        writer.writerows(repeatresults['Model'])
        writer.writerows(growrateresults['Random'])
        writer.writerows(growrateresults['Model'])
        writer.writerows(matchrateresults['Random'])
        writer.writerows(matchrateresults['Model'])

    while True:
        plt.pause(3)


# experiment()
modelAgent = GraphingAgent(random=False)
modelAgent.main(40, 2, 5)

while True:
    plt.pause(3)
