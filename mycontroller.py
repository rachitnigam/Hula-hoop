#!/usr/bin/env python2
import argparse, re, grpc, os, sys, json, subprocess
from time import sleep
import networkx as nx

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'utils/'))
import run_exercise
import p4runtime_lib.bmv2
from p4runtime_lib.switch import ShutdownAllSwitchConnections
import p4runtime_lib.helper
from p4runtime_lib.convert import decodeMac, decodeIPv4

# Turn on dry run mode
debug = False

# Directory for storing simple_switch_CLI commands
ssc_dir = "config/"

def printGrpcError(e):
    """
    Helper function to print a GRPC error

    :param e: the error object
    """

    print "gRPC Error:", e.details(),
    status_code = e.code()
    print "(%s)" % status_code.name,
    traceback = sys.exc_info()[2]
    print "[%s:%d]" % (traceback.tb_frame.f_code.co_filename, traceback.tb_lineno)

def load_topology(topo_file_path):
    """
    Helper function to load a topology

    :param topo_file_path: the path to the JSON file containing the topology
    """

    switch_number = 0
    switches = {}
    with open(topo_file_path) as topo_data:
        j = json.load(topo_data)
    json_hosts = j['hosts']
    json_switches = j['switches'].keys()
    json_links = run_exercise.parse_links(j['links'])
    mn_topo = run_exercise.ExerciseTopo(json_hosts, json_switches, json_links, "logs")
    for switch in mn_topo.switches():
        switch_number += 1
        bmv2_switch = p4runtime_lib.bmv2.Bmv2SwitchConnection(
            name=switch,
            address="127.0.0.1:%d" % (50050 + switch_number),
            device_id=(switch_number - 1),
            proto_dump_file="logs/%s-p4runtime-requests.txt" % switch)
        switches[switch] = bmv2_switch

    return (switches, mn_topo)

# Generate a simple UID for dst_id of each host
def host_to_dst_id(hosts):
    return dict(zip(hosts, range(1, len(hosts) + 1)))

def install_rules(mn_topo, switches, p4info_helper):
    # Keep track of links already installed.
    ingress_installed = set()
    egress_installed = set()
    links_installed = set()
    G = nx.Graph()
    G.add_edges_from(mn_topo.links())
    host_dst_ids = host_to_dst_id(mn_topo.hosts())
    host_pairs = [(h1, h2) for h1 in mn_topo.hosts() for h2 in mn_topo.hosts() if h1 != h2]
    for (h1, h2) in host_pairs:
        path = nx.shortest_path(G, source=h1, target=h2)

        # Shortest path must contain at least one switch
        if len(path) < 3:
            raise Exception("Could not find a path from %s to %s" % (h1, h2))

        # Install the tunnel header at network ingress
        s = path[1]
        (h2_ip, _) = mn_topo.nodeInfo(h2)['ip'].split('/')
        if (h2_ip, s) not in ingress_installed:
            ingress_installed.add((h2_ip, s))
            packet_add_tunnel_header = p4info_helper.buildTableEntry(
                table_name="MyIngress.ipv4_lpm",
                match_fields={
                    "hdr.ipv4.dstAddr": (h2_ip, 32)
                },
                action_name="MyIngress.myTunnel_ingress",
                action_params={
                    "dst_id": host_dst_ids[h2],
                })
            switches[s].WriteTableEntry(packet_add_tunnel_header, debug)

        # Install s1 -> s2 for all s1, s2 in the path
        for i in xrange(1, len(path) - 2):
            (s1, s2) = (path[i], path[i+1])
            if (s1, s2, h2) in links_installed:
                continue
            links_installed.add((s1, s2, h2))
            (egress_port, _) = mn_topo.port(s1, s2)
            packet_tunnel_forward = p4info_helper.buildTableEntry(
                table_name="MyIngress.myTunnel_exact",
                match_fields={
                    "hdr.myTunnel.dst_id": host_dst_ids[h2]
                },
                action_name="MyIngress.myTunnel_forward",
                action_params={
                    "port": egress_port,
                })
            switches[s1].WriteTableEntry(packet_tunnel_forward, debug)

        # Strip tunnel header and forward to dst
        s2 = path[-2]
        if ((s2, h2) not in egress_installed):
            egress_installed.add((s2, h2))
            (egress_port, _) = mn_topo.port(s2, h2)
            packet_final_hop = p4info_helper.buildTableEntry(
                table_name="MyIngress.myTunnel_exact",
                match_fields={
                    "hdr.myTunnel.dst_id": host_dst_ids[h2]
                },
                action_name="MyIngress.myTunnel_egress",
                action_params={
                    "dstAddr": mn_topo.nodeInfo(h2)['mac'],
                    "port": egress_port
                })
            switches[s2].WriteTableEntry(packet_final_hop, debug)

def write_simple_switch_config(name, contents):
    file = open(ssc_dir + name, "w")
    file.write(contents)

def mcast_grp_command(mcast_id, port_ids, handle_id):
    port_seq = " ".join(str(e) for e in port_ids)
    create = "mc_mgrp_create " + str(mcast_id)
    node = "mc_node_create 0 " + port_seq
    assoc = "mc_node_associate " + str(mcast_id) + " " + str(handle_id)
    return create + "\n" + node + "\n" + assoc

# Assumes switches are numbered as s\d+
def run_mcast_commands(switches):
    switch_reg = re.compile(r"^s(\d+)$")
    for switch in switches:
        switch_port = 9090 + int(switch_reg.search(switch).group(1))
        cmd = "simple_switch_CLI --thrift-port %d < config/%s" % (switch_port, switch)
        print "Running", cmd
        print(subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True))

# Creates multicast groups. The [i]th mcast group forwards packets to all
# ports except [i].
def install_mcast(mn_topo, switches, p4info_helper):
    G = nx.Graph()
    G.add_edges_from(mn_topo.links())
    for switch in mn_topo.switches():
        command = ""
        adjacents = map(lambda (_, a): a, G.edges(switch))
        for adj in adjacents:
            mcast_adjs = filter(lambda a: a != adj, adjacents)
            mcast_ports = map(lambda a: mn_topo.port(switch, a)[0], mcast_adjs)
            ingress_port = mn_topo.port(switch, adj)[0]
            cmd = mcast_grp_command(ingress_port, mcast_ports, switches[switch].getAndUpdateHandleId())
            command += (cmd + "\n")
        write_simple_switch_config(switch, command)
    run_mcast_commands(mn_topo.switches())

def install_smart_mcast(mn_topo, switches, p4info_helper):
    # Note(rachit): Hosts are always considered downstream.
    def is_upstream(x, y):
        return x[0] == y[0] and int(x[1]) < int(y[1])

    G = nx.Graph()
    G.add_edges_from(mn_topo.links())
    for switch in mn_topo.switches():
        command = ""
        adjacents = map(lambda (_, a): a, G.edges(switch))
        for adj in adjacents:
            mcast_adjs = None
            # If the packet came from an upstream link, cast it to only downstream links
            if is_upstream(switch, adj):
                mcast_adjs = filter(lambda a: not is_upstream(switch, a), adjacents)
            # If the packet came from a downstream link, cast it at all other links.
            else:
                mcast_adjs = filter(lambda a: a != adj, adjacents)

            mcast_ports = map(lambda a: mn_topo.port(switch, a)[0], mcast_adjs)
            ingress_port = mn_topo.port(switch, adj)[0]
            cmd = mcast_grp_command(ingress_port, mcast_ports, switches[switch].getAndUpdateHandleId())
            command += (cmd + "\n")
        write_simple_switch_config(switch, command)
    run_mcast_commands(mn_topo.switches())


def main(p4info_file_path, bmv2_file_path, topo_file_path):
    # Instantiate a P4Runtime helper from the p4info file
    p4info_helper = p4runtime_lib.helper.P4InfoHelper(p4info_file_path)

    try:
        # Load the topology from the JSON file
        switches, mn_topo = load_topology(topo_file_path)

        # Establish a P4 Runtime connection to each switch
        for bmv2_switch in switches.values():
            bmv2_switch.MasterArbitrationUpdate()
            print "Established as controller for %s" % bmv2_switch.name

        # Load the P4 program onto each switch
        for bmv2_switch in switches.values():
            bmv2_switch.SetForwardingPipelineConfig(p4info=p4info_helper.p4info,
                                                    bmv2_json_file_path=bmv2_file_path)
            print "Installed P4 Program using SetForwardingPipelineConfig on %s" % bmv2_switch.name

        install_rules(mn_topo, switches, p4info_helper)
        install_smart_mcast(mn_topo, switches, p4info_helper)

    except KeyboardInterrupt:
        print " Shutting down."
    except grpc.RpcError as e:
        printGrpcError(e)

    ShutdownAllSwitchConnections()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='P4Runtime Controller')
    parser.add_argument('--p4info', help='p4info proto in text format from p4c',
                        type=str, action="store", required=False,
                        default='./build/switch.p4info')
    parser.add_argument('--bmv2-json', help='BMv2 JSON file from p4c',
                        type=str, action="store", required=False,
                        default='./build/switch.json')
    parser.add_argument('--topo', help='Topology file',
                        type=str, action="store", required=False,
                        default='topology.json')
    args = parser.parse_args()

    if not os.path.exists(args.p4info):
        parser.print_help()
        print "\np4info file not found: %s\nHave you run 'make'?" % args.p4info
        parser.exit(1)
    if not os.path.exists(args.bmv2_json):
        parser.print_help()
        print "\nBMv2 JSON file not found: %s\nHave you run 'make'?" % args.bmv2_json
        parser.exit(1)
    if not os.path.exists(args.topo):
        parser.print_help()
        print "\nTopology file not found: %s" % args.topo
        parser.exit(1)
    main(args.p4info, args.bmv2_json, args.topo)
