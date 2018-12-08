#!/usr/bin/env python

'''This file generates clos-style fattrees in dot notation according to the
paper: "A Scalable Commodity Data Center Network Architecture" by Al-Fares,
Loukissas and Vahdat.
'''
'''Modified version of
https://github.com/frenetic-lang/frenetic/blob/master/topology/scripts/fattree.py
'''
import argparse, json
import networkx as nx
from topolib import *

def mk_topo(pods, bw='1Gbps'):
    num_hosts         = (pods ** 3)/4
    num_agg_switches  = pods * pods
    num_core_switches = (pods * pods)/4

    if num_agg_switches > 100:
       raise Exception("Naming convention doesnt work with more than 100 aggregation switches.")

    hosts = [('h' + str(i), {})
             for i in range (1, num_hosts + 1)]

    agg_switches = [('s' + str(i), {
        'type':'switch', 'level':'aggregation', 'id':i
    }) for i in range(200, num_agg_switches + 200)]

    core_switches = [('s' + str(i), {
        'type':'switch', 'level':'core', 'id':i
    }) for i in range(300, num_core_switches + 300)]

    edge_num = 100
    for pod in range(pods):
        for sw in range(pods/2):
            agg_switches[(pod*pods) + sw][1]['level'] = 'edge'
            agg_switches[(pod*pods) + sw] = ("s" + str(edge_num), agg_switches[(pod*pods) + sw][1])
            edge_num += 1

    edge_switches = filter(lambda sw: sw[1]['level'] == 'edge', agg_switches)
    agg_only_switches = filter(lambda sw: sw[1]['level'] != 'edge', agg_switches)


    g = nx.Graph()
    g.add_nodes_from(hosts)
    g.add_nodes_from(core_switches)
    g.add_nodes_from(agg_switches)

    host_offset = 0
    for pod in range(pods):
        core_offset = 0
        for sw in range(pods/2, pods):
            switch = agg_switches[(pod*pods) + sw][0]
            # Connect to core switches
            for port in range(pods/2, pods):
                core_switch = core_switches[core_offset][0]
                g.add_edge(switch,core_switch)
                g.add_edge(core_switch,switch)
                core_offset += 1

            # Connect to aggregate switches in same pod
            for port in range(pods/2):
                lower_switch = agg_switches[(pod*pods) + port][0]
                g.add_edge(switch,lower_switch)
                g.add_edge(lower_switch,switch)

        for sw in range(pods/2):
            switch = agg_switches[(pod*pods) + sw][0]
            # Connect to hosts
            for port in range(pods/2):
                host = hosts[host_offset][0]
                # All hosts connect on port 0
                g.add_edge(switch,host)
                g.add_edge(host,switch)
                host_offset += 1

    a = nx.nx_agraph.to_agraph(g)
    a.add_subgraph(map(lambda (a, _): a, hosts), rank='same')
    a.add_subgraph(map(lambda (a, _): a, core_switches), rank='same')
    a.add_subgraph(map(lambda (a, _): a, agg_only_switches), rank='same')
    a.add_subgraph(map(lambda (a, _): a, edge_switches), rank='same')

    return a

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-p','--pods',type=int,action='store',dest='pods',
                        default=4,
                        help='number of pods (parameter k in the paper)')
    parser.add_argument('-b','--bandwidth',type=str,action='store',dest='bw',
                        default='1Gbps',
                        help='bandwidth of each link')
    parser.add_argument('-o', '--out', action='store',dest='output',
                        default=None,
                        help='file root to write to')

    return parser.parse_args()

if __name__ == '__main__':
    args = parse_args()
    topo = mk_topo(args.pods,args.bw)

    if args.output:
        nx.drawing.nx_agraph.write_dot(topo, args.output+'.dot')
        # draw_graph(topo, args.output+".png")
    else:
        links = topo.edges()
        hosts = filter(lambda n: n.startswith('h'), topo.nodes())
        sws = filter(lambda n: n.startswith('s'), topo.nodes())
        switches = {}
        for switch in sws:
            switches[switch] = {}
        topology = {"hosts": hosts, "switches": switches, "links": links}
        print json.dumps(topology, sort_keys=True, indent=4, separators=(',', ': '))
